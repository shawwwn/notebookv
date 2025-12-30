import datetime
import json
import dataclasses






@dataclasses.dataclass
class Notebook():
	owner_uid: int
	notebookid: int
	notebook_name: str
	meta: dict

	def __init__(self, owner_uid: int, notebook_name='Unamed', notebookid=None, meta={}, vectorstore=None):
		assert owner_uid != 0
		self.owner_uid = owner_uid
		self.notebookid = notebookid
		self.notebook_name = notebook_name
		self.meta = meta
		self.vectorstore = None

	@staticmethod
	async def initDB(conn):
		cursor = await conn.cursor()
		print("init Notebooks table")
		await cursor.executescript('''
			DROP TABLE IF EXISTS Notebooks;
			CREATE TABLE Notebooks (
				nbid INTEGER PRIMARY KEY AUTOINCREMENT UNIQUE,
				name TEXT,
				owner INTEGER,
				meta TEXT,
				vectorstore BLOB
			);
			INSERT INTO Notebooks (owner, meta) VALUES (1,
				json_insert('{}',
					'$.created_at', CURRENT_TIMESTAMP));
			CREATE TABLE notebook_1 (
				docid INTEGER PRIMARY KEY AUTOINCREMENT,
				title TEXT,
				content TEXT,
				lastedit TIMESTAMP,
				meta TEXT,
				dirty INTEGER,
				chunk_embs BLOB,
				title_emb BLOB,
				chunk_spans TEXT
			);
			INSERT INTO notebook_1 (title, content, lastedit, meta, dirty) VALUES ('hello world', 'your first note', CURRENT_TIMESTAMP, '{}', 1);
		''')
		await cursor.close()


	@classmethod
	async def createNotebook(cls, request, owner_uid, notebook_name='Unamed'):
		cursor = await request.app.state.db_conn.cursor()
		try:
			await cursor.execute(f'''
				INSERT INTO Notebooks (owner, name, meta)
					VALUES (
						'{owner_uid}',
						'{notebook_name}',
						json_insert('{{}}', '$.created_at', CURRENT_TIMESTAMP)
					)
					RETURNING nbid;
			''')
			row = await cursor.fetchone()
			if row:
				nbid = int(row[0])
		except:
			nbid = None
			await cursor.close()
			return None

		# create notebook table
		tablename = f'notebook_{nbid}'
		await cursor.executescript(f'''
			CREATE TABLE {tablename} (
				docid INTEGER PRIMARY KEY AUTOINCREMENT,
				title TEXT,
				content TEXT,
				lastedit TIMESTAMP,
				meta TEXT,
				dirty INTEGER,
				chunk_embs BLOB,
				title_emb BLOB,
				chunk_spans TEXT
			);
			INSERT INTO {tablename} (title, content, lastedit, meta, dirty) VALUES ('hello', 'your first note', CURRENT_TIMESTAMP, '{{}}', 1);
		''')

		print(f'user#{owner_uid} created notebook#{nbid}')
		await cursor.close()
		return nbid

	@classmethod
	async def fetchUserNotebooks(cls, request, uid):
		cursor = await request.app.state.db_conn.cursor()
		await cursor.execute(f'''
			SELECT nbid, name, meta
			FROM Notebooks
			WHERE owner={uid};
		''')
		rows = await cursor.fetchall()
		await cursor.close()

		notebooks = []
		for row in rows:
			notebook = cls(uid, notebookid=row[0], notebook_name=row[1], meta=row[2])
			notebook.meta = None if not notebook.meta else json.loads(notebook.meta)
			notebooks.append(notebook)
		return notebooks
