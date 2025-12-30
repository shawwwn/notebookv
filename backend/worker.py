import asyncio
import json
import pickle
import datetime
import time

import aiosqlite
import anyio

import model
import config



async def note_scanner(app):
	"""
	Scan for notes that needs to be processed
	"""
	await anyio.sleep(1)
	print("note scanner: start")
	db_conn = app.state.db_conn
	while True:
		if app.state.should_exit is True:
			break
		try:
			cursor = await db_conn.cursor()

			# create missing vectorstore for notebook
			await cursor.execute(f'''
				SELECT
					nbid,
					CASE WHEN vectorstore IS NULL THEN TRUE ELSE FALSE END
				FROM Notebooks;
			''')
			rows = await cursor.fetchall()
			for nbid, vs_not_found in rows:
				if bool(vs_not_found):
					vs = await model.NotebookVectorStore.getVectorStore(nbid, db_conn)
					await model.NotebookVectorStore.saveDB(db_conn, vs, notebookid=nbid)

			# scan for unchunk notes
			for nbid, _ in rows:
				try:
					tablename = f'notebook_{nbid}'
					await cursor.execute(f'''
						SELECT count(*) FROM sqlite_master WHERE type='table' AND name='{tablename}';
					''')
					table_exists = bool((await cursor.fetchone())[0])
					if table_exists:

						# scan notebook table
						nb_dirty = False
						await cursor.execute(f'''
							SELECT docid
							FROM {tablename}
							WHERE dirty = 1
								OR title_emb IS NULL OR title_emb = ''
								OR chunk_spans IS NULL OR chunk_spans = ''
								OR chunk_embs IS NULL OR chunk_embs = ''
								OR meta IS NULL OR meta = ''
								OR json_extract(meta, '$.embed_d') != {config.LLM_EMBED_D}
								OR json_extract(meta, '$.n_chunk') == NULL;
						''')
						docids = await cursor.fetchall()
						for docid, in docids:
							nb_dirty = True
							await app.state.chunk_queue.put((nbid, docid))

						# signal to rebuild notebook vectorstore
						if not nb_dirty:
							await app.state.rebuild_queue.put(nbid)

				except:
					print("note scanner: error during notebook scan")
					pass

			await cursor.close()
			print('note scanner: sleep')
			await anyio.sleep(600)  # run every 10 mins

		except anyio.get_cancelled_exc_class():
			print("note scanner: cancelled")
			break

	print("note scanner: exit")


def note_chunker(app):
	"""
	Consume queue for next note to chunk.
	Proceed to chunk note.
	Save result to database after done.
	"""
	async def _get_next_note(app):
		# this function runs inside main thread context
		notebookid, noteid = await app.state.chunk_queue.get()
		if app.state.should_exit is True:
			return None, None
		return notebookid, noteid

	async def _chunk(app, db_conn2, notebookid, noteid, task_status=None):
		# this function runs in worker thread context
		print(f"note#{notebookid}/{noteid}: chunk - start")

		note = await model.Note.db_load(db_conn2, notebookid, noteid)
		rets = await note.make_chunks()
		if not rets:
			print(f"note#{notebookid}/{noteid}: chunk - failed")
			return
		chunks, chunk_spans, chunk_embs, title_emb = rets

		async def _store_chunks(app):
			# this function runs inside main thread context
			await note.db_store_chunks(app.state.db_conn, title_emb, chunk_embs, chunk_spans)
			await note.db_store_cols(app.state.db_conn,
				['dirty', 'meta'],
				[False, f"json_set(CASE WHEN meta IS NULL THEN '{{}}' ELSE meta END, '$.n_chunk', {len(chunks)}, '$.embed_d', {len(title_emb)})"],
				directly=True)
			vs = await model.NotebookVectorStore.getVectorStore(notebookid, app.state.db_conn)
			if vs.index.is_trained:
				vs.add(noteid, chunk_embs, chunk_spans, title_emb)
				await model.NotebookVectorStore.saveDB(app.state.db_conn, vs, notebookid=notebookid)
			await app.state.db_conn.commit()
			print(f"note#{notebookid}/{noteid}: chunk - complete")

		anyio.from_thread.run(_store_chunks, app)

	# --------------------------------------
	time.sleep(1)
	print("note chunker: start")
	db_conn2 = asyncio.run(model.db_init(config.DB_PATH))

	while True:
		notebookid, noteid = anyio.from_thread.run(_get_next_note, app)
		if not notebookid or not noteid:
			break  # exit signal

		asyncio.run(_chunk(app, db_conn2, notebookid, noteid))
		# anyio.run(_chunk, app, db_conn2, notebookid, noteid)
		# anyio.run(app.state.tg.start, _chunk, app, db_conn2, notebookid, noteid)

	asyncio.run(db_conn2.commit())
	asyncio.run(db_conn2.close())

	print("note chunker: exit")







async def _chunk_all(app, notebookid):
	"""
	Continuously chunking all notes under notebook
	"""
	vs = await model.NotebookVectorStore.getVectorStore(notebookid, app.state.db_conn)
	print(vs.emb_id_map)
	print(vs.noteid_map)

	db_conn = model.db_init(config.DB_PATH)

	tablename = "notebook_" + str(notebookid)
	cursor = await db_conn.cursor()
	await cursor.execute(f'''
		SELECT docid
		FROM {tablename}
		WHERE title_emb IS NULL OR dirty = 1;
	''')
	rows = await cursor.fetchall()
	await cursor.close()
	docids = [r[0] for r in rows]
	print(f"there are {len(docids)} notes to chunk")


	for noteid in docids:
		import threading
		if threading.main_thread().is_alive() is False or app.state.should_exit is True:
			break

		print()
		noteid = int(noteid)
		note = await model.Note.db_load(db_conn, notebookid, noteid)
		print(note)
		chunks, chunk_spans, chunk_embs, title_emb = await note.make_chunks()
		await note.db_store_chunks(db_conn, title_emb, chunk_embs, chunk_spans)
		await note.db_store_cols(db_conn,
			['dirty', 'meta'],
			[False, f"json_set(CASE WHEN meta IS NULL THEN '{{}}' ELSE meta END, '$.n_chunk', {len(chunks)}, '$.embed_d', {len(title_emb)})"],
			directly=True)
		db_conn.commit()

		if vs.index.is_trained:
			vs.add(noteid, chunk_embs, chunk_spans, title_emb)
			await model.NotebookVectorStore.saveDB(db_conn, vs, notebookid=notebookid)

		await anyio.sleep(1)

	print("done!")





async def index_rebuilder(app):
	"""
	Consume queue for next notebook to scan.
	Scan all notes within the notebook and determine whether we should rebuild
	notebook's faiss index.
	Proceed to rebuild faiss index.
	"""
	await anyio.sleep(3)
	print("index rebuilder: start")
	while True:
		notebookid = await app.state.rebuild_queue.get()
		print(f"vectorstore#{notebookid}: rebuild check")
		if notebookid is None or app.state.should_exit is True:
			break

		vs = await model.NotebookVectorStore.getVectorStore(notebookid, app.state.db_conn)
		tablename = f'notebook_{notebookid}'
		cursor = None

		# Check if notebook's faiss index needs rebuilding
		rebuild = False
		if vs.emb_count==0 or not vs.index.is_trained:
			# empty faiss index
			cursor = await app.state.db_conn.cursor() if not cursor else cursor
			await cursor.execute(f'''
				SELECT
					docid, json_extract(meta, '$.n_chunk')
				FROM {tablename}
				WHERE dirty = 0
					AND meta IS NOT NULL AND meta != '{{}}'
					AND chunk_embs IS NOT NULL
					AND json_extract(meta, '$.embed_d') == {config.LLM_EMBED_D};
			''')
			rows = await cursor.fetchall()
			n_total = 0
			for docid, n_chunk in rows:
				n_total += n_chunk

			if n_total > vs.nlist:
				rebuild = True
		else:
			# non-empty faiss index
			gap = datetime.datetime.utcnow() - vs.last_rebuild
			if vs.modifies>25:
				rebuild = True
			elif vs.modifies>10 and gap>datetime.timedelta(days=1):
				rebuild = True
			elif vs.modifies>0 and gap>datetime.timedelta(days=10):
				rebuild = True

		# Rebuilding
		if rebuild:
			print(f"vectorstore#{notebookid}: rebuilding ...")

			cursor = await app.state.db_conn.cursor() if not cursor else cursor
			await cursor.execute(f'''
				SELECT
					docid, chunk_embs, chunk_spans, title_emb
				FROM {tablename}
				WHERE dirty = 0
					AND meta IS NOT NULL AND meta != '{{}}'
					AND chunk_embs IS NOT NULL
					AND json_extract(meta, '$.embed_d') == {config.LLM_EMBED_D};
			''')
			rows = await cursor.fetchall()

			all_embs = []
			rows_uncompressed = []
			for docid, chunk_embs, chunk_spans, title_emb in rows:
				noteid = int(docid)
				chunk_embs = pickle.loads(chunk_embs)
				chunk_spans = json.loads(chunk_spans)
				title_emb = pickle.loads(title_emb)
				rows_uncompressed.append((noteid, chunk_embs, chunk_spans, title_emb))
				all_embs.extend(chunk_embs)

			# rebuild
			vs.clear()
			vs.train(all_embs)
			for noteid, chunk_embs, chunk_spans, title_emb in rows_uncompressed:
				vs.add(noteid, chunk_embs, chunk_spans, title_emb)
			vs.modifies = 0
			vs.last_rebuild = datetime.datetime.utcnow()
			print(f"vectorstore#{notebookid}: rebuilding successful")

			await model.NotebookVectorStore.saveDB(app.state.db_conn, vs, notebookid=notebookid)

		else:
			print(f"vectorstore#{notebookid}: no need to rebuild")

		# print(vs.emb_count)
		# print(vs.modifies)
		# print(vs._get_invlists())
		# print(vs.noteid_map)

		if cursor:
			await cursor.close()

	print("index rebuilder: exit")
