import json
import datetime
import dataclasses
import pickle
import os

import sqlite3
import aiosqlite

import nlp
import config

from model.user import User
from model.vectorstore import NotebookVectorStore
from model.notebook import Notebook




async def db_init(db_path):
	first_run = True if not os.path.exists(db_path) else False

	aiosqlite.register_converter('DATETIME', sqlite3.converters['TIMESTAMP'])
	conn = await aiosqlite.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
	await conn.enable_load_extension(True)
	await conn.load_extension(config.SQLITE_TOKENIZER)
	print(".libsimple loaded")

	if first_run:
		print("first run")
		await User.initDB(conn)
		await Notebook.initDB(conn)
		await db_init_table_fts(conn, "notebook_1", fts_tokenizer='simple')
	return conn


async def db_rebuild_table_fts(conn, tablename):
	cursor = await conn.cursor()
	tablename_fts = tablename + '_fts'
	await cursor.execute(f'''INSERT INTO {tablename_fts}({tablename_fts}) VALUES('rebuild');''')
	await cursor.close()


async def db_init_table_fts(conn, tablename, fts_tokenizer=''):
	cursor = await conn.cursor()
	tablename_fts = tablename + '_fts'
	if fts_tokenizer:
		fts_tokenizer = f"tokenize = '{fts_tokenizer}',"

	# build FTS index on a table
	print(f'init fts index for table "{tablename}"')
	await cursor.executescript(f'''
		DROP TABLE IF EXISTS {tablename_fts};
		CREATE VIRTUAL TABLE {tablename_fts} USING fts5(
			title,
			content,
			{fts_tokenizer}
		content='{tablename}', content_rowid='docid');

		-- hooks to sync FTS index with its content table
		DROP TRIGGER IF EXISTS {tablename_fts}_ai;
		DROP TRIGGER IF EXISTS {tablename_fts}_ad;
		DROP TRIGGER IF EXISTS {tablename_fts}_au;
		CREATE TRIGGER {tablename_fts}_ai AFTER INSERT ON {tablename} BEGIN
			INSERT INTO {tablename_fts}(rowid, title, content) VALUES (new.docid, new.title, new.content);
		END;
		CREATE TRIGGER {tablename_fts}_ad AFTER DELETE ON {tablename} BEGIN
			INSERT INTO {tablename_fts}({tablename_fts}, rowid, title, content) VALUES('delete', old.docid, old.title, old.content);
		END;
		CREATE TRIGGER {tablename_fts}_au AFTER UPDATE ON {tablename} BEGIN
			INSERT INTO {tablename_fts}({tablename_fts}, rowid, title, content) VALUES('delete', old.docid, old.title, old.content);
			INSERT INTO {tablename_fts}(rowid, title, content) VALUES (new.docid, new.title, new.content);
		END;

		-- build FTS index from its content table
		INSERT INTO {tablename_fts}(rowid, title, content)
			SELECT docid, title, content FROM {tablename};
	''')
	await cursor.close()





@dataclasses.dataclass
class Note():
	notebookid: str
	noteid: str
	title: str
	textcontent: str
	lastedit: datetime.datetime
	meta: dict
	dirty: bool=False

	async def make_chunks(self):
		"""
		Chunking note text
		"""
		print("chunk note#%s/%s" % (self.notebookid, self.noteid))
		nlp_model = nlp.initNLP()
		doc = nlp_model(self.textcontent)
		sentences, spans = nlp.splitDoc(doc)
		print("split note into %d sentences" % len(sentences))

		sent_embs = await nlp.asyncGetEmbedLLM(sentences)
		if not sent_embs:
			print("failed getting sentence embeddings")
			return None

		chunks, chunk_spans = nlp.makeChunks(sentences, spans, sent_embs)
		print("group sentences into %d chunks" % len(chunks))

		chunk_embs = await nlp.asyncGetEmbedLLM([self.title, *chunks])
		if not chunk_embs:
			print("failed getting chunk embeddings")
			return None

		title_emb = chunk_embs[0]
		chunk_embs = chunk_embs[1:]
		return chunks, chunk_spans, chunk_embs, title_emb

	async def db_store_chunks(self, db_conn, title_emb, chunk_embs, chunk_spans):
		"""
		Save chunks' embeddings and spans to database
		"""
		tablename = 'notebook_' + str(self.notebookid)
		b_chunk_embs = pickle.dumps(chunk_embs)
		b_title_emb = pickle.dumps(title_emb)
		js_chunk_spans = json.dumps(chunk_spans)
		cursor = await db_conn.cursor()
		await cursor.execute(f'''
			UPDATE {tablename}
			SET
				title_emb = ?,
				chunk_embs = ?,
				chunk_spans = ?
			WHERE docid = {self.noteid};
		''', (b_title_emb, b_chunk_embs, js_chunk_spans))
		await cursor.close()
		print("saved %d chunks and their embeddings to note#%s/%s" % (len(chunk_embs), self.notebookid, self.noteid))

	async def db_fetch_cols(self, db_conn, col_names):
		"""
		Load one or more columns from database's note entry
		"""
		if isinstance(col_names, str):
			col_names = [col_names]

		tablename = 'notebook_' + str(self.notebookid)
		cursor = await db_conn.cursor()
		await cursor.execute(f'''
			SELECT {','.join(col_names)}
			FROM {tablename}
			WHERE docid = {self.noteid};
		''')
		result = await cursor.fetchone()
		await cursor.close()
		return result

	async def db_store_cols(self, db_conn, col_names, values, directly=False):
		"""
		Store/update one or more columns to database's note entry
		"""
		if isinstance(col_names, str):
			col_names = [col_names]
			values = [values]

		tablename = 'notebook_' + str(self.notebookid)
		cursor = await db_conn.cursor()
		if not directly:
			await cursor.execute(f'''
				UPDATE {tablename}
				SET {','.join([f"{name} = ?" for name in col_names])}
				WHERE docid = {self.noteid};
			''', values)
		else:
			await cursor.execute(f'''
				UPDATE {tablename}
				SET {','.join([f"{name} = {value}" for name, value in zip(col_names, values)])}
				WHERE docid = {self.noteid};
			''')
		await cursor.close()

	@classmethod
	async def db_load(cls, db_conn, notebookid, noteid):
		"""
		Load essential data from database and construct a Note object
		"""
		notebookid = str(notebookid)
		noteid = str(noteid)
		tablename = 'notebook_' + str(notebookid)
		cursor = await db_conn.cursor()
		await cursor.execute(f'''
			SELECT
				CAST(docid AS TEXT), title, content,
				CAST(strftime('%s', lastedit) AS INTEGER),
				meta, dirty
			FROM {tablename}
			WHERE docid = {noteid};
		''')
		row = await cursor.fetchone()
		await cursor.close()
		print("fetched note#%s/%s" % (notebookid, noteid))
		if not row:
			return None

		assert(row[0] == noteid)
		note = cls(noteid=noteid,
				notebookid=notebookid,
				title=row[1],
				textcontent=row[2],
				lastedit=row[3],
				meta=json.loads(row[4] if row[4] else '{}'),
				dirty=bool(row[5]))
		return note

	@classmethod
	async def db_update(cls, db_conn, notebookid, noteid, title, textcontent):
		"""
		Update database's note entry
		"""
		print(f"update note#{notebookid}/{noteid}")
		tablename = f'notebook_{notebookid}'
		cursor = await db_conn.cursor()
		await cursor.execute(f'''
			UPDATE {tablename}
			SET
				title = ?,
				content = ?,
				lastedit = CURRENT_TIMESTAMP,
				dirty = 1
			WHERE docid = {noteid};
		''', (title, textcontent))
		await cursor.close()
		if cursor.rowcount!=1:
			print(f"update note#{notebookid}/{noteid} - failed")
			return False
		return True

	@classmethod
	async def db_delete(cls, db_conn, notebookid, noteid):
		"""
		Delete from database
		"""
		print(f"delete note#{notebookid}/{noteid}")
		tablename = f'notebook_{notebookid}'
		cursor = await db_conn.cursor()
		await cursor.execute(f'''
			DELETE FROM {tablename}
			WHERE docid = {noteid};
		''')
		await cursor.close()

	@classmethod
	async def db_insert(cls, db_conn, notebookid, title, textcontent):
		"""
		Update database's note entry
		"""
		tablename = f'notebook_{notebookid}'
		cursor = await db_conn.cursor()
		await cursor.execute(f'''
			INSERT INTO {tablename} (title, content, lastedit, dirty)
			VALUES (?, ?, CURRENT_TIMESTAMP, 0);
		''', (title, textcontent))
		noteid = cursor.lastrowid
		await cursor.close()
		if noteid:
			print(f"inserted note#{notebookid}/{noteid}")
			return noteid
		return None
