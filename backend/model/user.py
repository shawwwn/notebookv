import datetime

import starlette_login.mixins






# cached user instances
user_pool = {}


# @dataclasses.dataclass
class User(starlette_login.mixins.UserMixin):

	def __init__(self, uid, username, password, lastlogin, since, isadmin):
		self.uid = uid
		self.username = username
		self.password = password
		self.lastlogin = lastlogin
		self.since = since
		self.isadmin = isadmin

	@staticmethod
	async def initDB(conn):
		cursor = await conn.cursor()
		print("init Users table")
		await cursor.executescript('''
			DROP TABLE IF EXISTS Users;
			CREATE TABLE Users (
				uid INTEGER PRIMARY KEY AUTOINCREMENT UNIQUE,
				username TEXT UNIQUE,
				password TEXT,
				lastlogin TIMESTAMP,
				since TIMESTAMP,
				isadmin INTEGER
			);
			INSERT INTO Users (username, password, lastlogin, since, isadmin)
				VALUES ('admin', '1234', NULL, CURRENT_TIMESTAMP, TRUE)
		''')
		await cursor.close()

	@property
	def identity(self) -> int:
		return self.uid

	@property
	def display_name(self) -> str:
		return self.username

	@property
	def is_authenticated(self) -> bool:
		return True

	async def update_lastlogin(self, request):
		self.lastlogin = datetime.datetime.now()
		cursor = await request.app.state.db_conn.cursor()
		await cursor.execute(f"UPDATE Users SET lastlogin = CURRENT_TIMESTAMP WHERE uid = {self.uid};")
		await cursor.close()
		return True

	@classmethod
	async def getUserByName(cls, request, username):
		username = str(username)
		if username in user_pool:
			return user_pool[username]

		cursor = await request.app.state.db_conn.cursor()
		await cursor.execute(f'''
			SELECT uid, username, password, lastlogin, since, isadmin
			FROM Users
			WHERE username = '{username}';
		''')
		row = await cursor.fetchone()
		await cursor.close()
		if not row:
			print("no such user")
			return None
		uid, username, password, lastlogin, since, isadmin = row
		user = cls(uid, username, password, lastlogin, since, isadmin)
		print("getUserByName:", user)
		user_pool[user.uid] = user
		user_pool[user.username] = user
		return user

	@classmethod
	async def getUserById(cls, request, uid):
		uid = int(uid)
		if uid in user_pool:
			return user_pool[uid]

		cursor = await request.app.state.db_conn.cursor()
		await cursor.execute(f'''
			SELECT uid, username, password, lastlogin, since, isadmin
			FROM Users
			WHERE uid = {uid};
		''')
		row = await cursor.fetchone()
		await cursor.close()
		if not row:
			print("no such user")
			return None
		uid, username, password, lastlogin, since, isadmin = row
		user = cls(uid, username, password, lastlogin, since, isadmin)
		print("getUserById:", user)
		user_pool[user.uid] = user
		user_pool[user.username] = user
		return user

	@classmethod
	async def createUser(cls, request, username, password, isadmin=False):
		"""
		return uid
		"""
		if not username or not password:
			return None

		uid = None
		try:
			cursor = await request.app.state.db_conn.cursor()
			await cursor.execute(f'''
				INSERT INTO Users (username, password, since, isadmin)
					VALUES ('{username}', '{password}', CURRENT_TIMESTAMP, '{int(isadmin)}')
					RETURNING uid;
			''')
			row = await cursor.fetchone()
			await cursor.close()
			await request.app.state.db_conn.commit()
			if row:
				uid = int(row[0])
		except:
			uid = None
		return uid
