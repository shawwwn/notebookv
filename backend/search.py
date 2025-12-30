import collections
import math

import nlp
import model


async def quick_search(request, notebookid, keyword, k=5, snippet_size=48, is_quoted=True):
	tablename = f"notebook_{notebookid}"
	tablename_fts = tablename+"_fts"

	cursor = await request.app.state.db_conn.cursor()
	format_title = f"simple_highlight({tablename_fts}, 0, '<b>', '</b>') title" if is_quoted else f"title"
	format_content = f"simple_snippet({tablename_fts}, 1, '<b>', '</b>', ' ... ', {snippet_size}) content" if is_quoted else f"simple_snippet({tablename_fts}, 1, '', '', '...', {snippet_size}) content"
	format_content = f"content" if snippet_size==-1 else format_content
	await cursor.execute(f'''
		SELECT
			rowid,
			{format_title},
			{format_content},
			simple_highlight_pos({tablename_fts}, 0),
			simple_highlight_pos({tablename_fts}, 1)
		FROM {tablename_fts} WHERE {tablename_fts} MATCH simple_query('{keyword}');
	''')
	rows = await cursor.fetchmany(size=k)
	await cursor.close()

	result = {
		'query': keyword,
		'size': len(rows),
		'result': [{
			'notebookid': notebookid,
			'noteid': str(r[0]),
			'title': r[1],
			'desc': r[2],
			'title_pos': r[3],
			'content_pos': r[4],
		} for r in rows],
	}

	return result



def snippet(text, bold_spans, highlight_spans, window=20):
	all_spans = sorted(bold_spans + highlight_spans)
	if len(all_spans)==0:
		return None

	clusters = []
	prev_s, prev_e = all_spans[0]
	for s, e in all_spans[1:]:
		if s <= prev_e + window * 2:
			prev_e = max(prev_e, e)
		else:
			clusters.append((prev_s, prev_e))
			prev_s, prev_e = s, e
	clusters.append((prev_s, prev_e))

	# tags
	tags = []
	for s, e in bold_spans:
		tags.append((s, 0, "b"))
		tags.append((e, 1, "b"))
	for s, e in highlight_spans:
		tags.append((s, 0, "h"))
		tags.append((e, 1, "h"))
	tags = sorted(tags, key=lambda tag: tag[0])


	snippets = []
	for cluster_start, cluster_end in clusters:
		snippet_start = max(0, cluster_start - window)
		snippet_end = min(len(text), cluster_end + window)
		snippet_text = text[snippet_start:snippet_end]

		def shift(tags):
			out = []
			for tag in tags:
				if tag[0] < snippet_start or tag[0] > snippet_end:
					continue
				out.append((tag[0]-snippet_start, tag[1], tag[2]))
			return out

		snippet_tags = shift(tags)
		# if snippet_tags==[]:
		# 	return ""

		def to_marker(tag):
			return f"<{tag[2]}>" if tag[1]==0 else f"</{tag[2]}>"

		result = []
		pos = snippet_tags[0][0]
		result.append(snippet_text[0:pos])
		result.append(to_marker(snippet_tags[0]))
		for tag in snippet_tags[1:]:
			result.append(snippet_text[pos:tag[0]])
			result.append(to_marker(tag))
			pos = tag[0]
		result.append(snippet_text[pos:])
		snippets.append(''.join(result))

	return snippets


async def vsearch(request, notebookid, keyword, k=10, search_title=True, search_fts=True):
	result = {}
	tablename = f"notebook_{notebookid}"

	search_vector = True
	vs = await model.NotebookVectorStore.getVectorStore(notebookid, request.app.state.db_conn)
	if not vs.index or vs.index.ntotal<=0 or not vs.index.is_trained:
		search_vector = False

	nids = set()
	cursor = await request.app.state.db_conn.cursor()
	rows = []

	def _parse_positions(text, pos_str) -> list[list[int, int], ...]:
		"""
		convert byte positions to string positions
		"""
		if not pos_str:
			return []
		codec = 'utf-8'
		b_text = text.encode(codec)

		positions = []
		pair = []
		b_pp = 0
		pp = 0
		for s in pos_str.replace(';', ',').split(','):
			s = s.strip()
			if len(s)==0:
				continue
			b_p = int(s)
			seg = b_text[b_pp:b_p].decode(codec)
			p = pp+len(seg)
			b_pp = b_p
			pp = p
			pair.append(p) # [start, end]
			if len(pair)>=2:
				positions.append(pair)
				pair = []
		return positions

	# fts search
	if search_fts:
		tablename_fts = tablename+"_fts"
		sql1 = f"simple_highlight_pos({tablename_fts}, 0)," if search_title else "'',"
		sql2 = f"'\"{keyword}\"'" if search_title else f"'-title:\"{keyword}\"'"
		await cursor.execute(f'''
			SELECT
				rowid,
				rank,
				{sql1}
				simple_highlight_pos({tablename_fts}, 1)
			FROM {tablename_fts}
			WHERE {tablename_fts} MATCH {sql2}
			ORDER BY rank
			LIMIT {k};
		''')
		rows = await cursor.fetchmany(size=k)

	# prepare fts positions
	fts_positions = collections.OrderedDict()
	for row in rows:
		docid = int(row[0])
		fts_positions[docid] = row
		nids.add(docid)

	# semantic search
	matches_content = []
	matches_title = []
	if search_vector:
		querys = ['This is a query about: '+keyword+'.']
		if search_title:
			querys.append(keyword)
		embs = await nlp.asyncGetEmbedLLM(querys)
		if not embs:
			search_vector = False
			print("llm server down!")
		else:
			D, I = vs.search([embs[0]], k=k)
			D = D[0]
			I = I[0]
			matches_content = [vs.emb_id_map[i] for i in I if i!=-1 and i in vs.emb_id_map]  # [(nid, [s, e]), ...]
			nids = {int(m[0]) for m in matches_content}  # set()
			orphan_eids = [i for i in I if i!=-1 and i not in vs.emb_id_map]
			if len(orphan_eids)>0:
				print("remove orphan eids:", orphan_eids)
				vs.index.remove_ids(vs._conv_nparray(orphan_eids))
				vs.modifies += len(orphan_eids)

			D2, I2 = None, None
			if search_title:
				D2, I2 = vs.search_title([embs[1]], k=k)
				D2 = D2[0]
				I2 = I2[0]
				matches_title = [int(vs.emb_id_map_title[i]) for i in I2 if i!=-1 and i in vs.emb_id_map_title]  # [nid, ...]
				nids.update(matches_title)
				orphan_title_eids = [i for i in I2 if i!=-1 and i not in vs.emb_id_map_title]
				if len(orphan_title_eids)>0:
					print("remove orphan title eids:", orphan_title_eids)
					vs.index_title.remove_ids(vs._conv_nparray(orphan_title_eids))
					vs.modifies += len(orphan_title_eids)

	# fetch all related notes
	nids = ','.join([str(nid) for nid in nids])
	await cursor.execute(f'''
		SELECT
			docid,
			title,
			content,
			CAST(strftime('%s', lastedit) AS INTEGER),
			meta
		FROM {tablename}
		WHERE docid in ({nids});
	''')
	rows = await cursor.fetchall()
	await cursor.close()

	fetched_notes = {}
	for row in rows:
		docid = int(row[0])
		fetched_notes[docid] = row

	# prepare fts search results
	fts_rank = collections.OrderedDict()
	if search_fts:
		for i, (nid, score, b_pos_title, b_pos_content) in enumerate(fts_positions.values()):
			if nid not in fetched_notes:
				# if we recently deleted a note and fts index hasn't updated yet
				continue
			row = fetched_notes[nid]
			title = row[1]
			content = row[2]
			str_pos_title = _parse_positions(title, b_pos_title)
			str_pos_content = _parse_positions(content, b_pos_content)
			fts_rank[nid] = {
				'rank': i+1,
				'score': score,
				'noteid': nid,
				'title': title,
				'title_pos': str_pos_title,
				'content_pos': str_pos_content,
			}

	# prepare content semantic search results
	content_rank = collections.OrderedDict()
	if search_vector:
		for i, (nid, [s, e]) in enumerate(matches_content):
			if nid not in fetched_notes:
				# nid has been deleted
				continue
			row = fetched_notes[nid]
			if nid in content_rank:
				r = content_rank[nid]
				r['chunk_pos'].append([s, e])
				r['score'] += float(D[i]) / math.sqrt(len(r['chunk_pos']))
			else:
				content_rank[nid] = {
					'score': float(D[i]),
					'noteid': nid,
					'title': row[1],
					'chunk_pos': [[s, e]],
				}
		content_rank = collections.OrderedDict(collections.OrderedDict(sorted(content_rank.items(), key=lambda item: item[1]['score'], reverse=True)))
		for i, v in enumerate(content_rank.values()):
			v['rank'] = i+1

	# prepare title semantic search results
	title_rank = collections.OrderedDict()
	if search_vector and search_title:
		for i, nid in enumerate(matches_title):
			if nid not in fetched_notes:
				# nid has been deleted
				continue
			row = fetched_notes[nid]
			title_rank[nid] = {
				'rank': i+1,
				'score': float(D2[i]),
				'noteid': nid,
				'title': row[1],
			}

	# merge both content and title semantic search results
	result_semantic = collections.OrderedDict()
	if search_vector and content_rank:
		result_content = content_rank
		if title_rank:
			result_title = title_rank
			for k, v in result_content.items():
				v2 = v.copy()
				if k in result_title:
					v2['score'] += result_title[k]['score']/2
					v2['title_vmatch'] = True
				else:
					v2['title_vmatch'] = False
				result_semantic[k] = v2
			for k, v in result_title.items():
				if k in result_semantic:
					continue
				v2 = v.copy()
				v2['score'] /= 2
				v2['title_vmatch'] = True
				result_semantic[k] = v2
			result_semantic = collections.OrderedDict(collections.OrderedDict(sorted(result_semantic.items(), key=lambda item: item[1]['score'], reverse=True)))

	# merge fts result with semantic result
	merged_rank = []
	i = 0

	# first take 3/5 of FTS results
	split_idx = int(k*3/5) if search_vector else k
	for k, v in fts_rank.items():
		v2 = v.copy()
		v2['rank'] = i+1
		if k in result_semantic:
			v3 = result_semantic.pop(k)
			v2['vscore'] = v3['score']
			if 'chunk_pos' in v3:
				v2['chunk_pos'] = v3['chunk_pos']
			if 'title_vmatch' in v3:
				v2['title_vmatch'] = v3['title_vmatch']
		merged_rank.append(v2)
		i += 1
		if i>=split_idx:
			break

	# fill the rest with semantic results
	for k, v in result_semantic.items():
		v2 = v.copy()
		v2['rank'] = i+1
		v2['vscore'] = v2.pop('score')
		if k in fts_rank:
			v3 = fts_rank.pop(k)
			v2['score'] = v3['score']
			v2['title_pos'] = v3['score']
			v2['content_pos'] = v3['content_pos']
		merged_rank.append(v2)
		i += 1
		if i>=k:
			break

	# add text content to merged results
	for r in merged_rank:
		row = fetched_notes[r['noteid']]
		r['content'] = row[2]
		r['lastedit'] = row[3]
		# chunk_pos = r.get('chunk_pos', [])
		# content_pos = r.get('content_pos', [])
		# r['snippet'] = snippet(fetched_notes[r['noteid']][2], content_pos, chunk_pos, window=100)

	result['ranking'] = merged_rank

	# setup vector index rebuild task for background workers
	if search_vector:
		if len(orphan_eids)>0 or len(orphan_title_eids):
			await model.NotebookVectorStore.saveDB(request.app.state.db_conn, vs, notebookid)
			await request.app.state.rebuild_queue.put(notebookid)

	return result
