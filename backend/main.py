import os
import asyncio
import typing
import json
import urllib.parse
import datetime
import requests
import dataclasses
import pickle
import contextlib
import collections
import math

import anyio
import anyio.from_thread
import starlette
import starlette.routing
import starlette.responses
import starlette.applications
import starlette.config
import starlette.datastructures
import starlette.staticfiles
import starlette.middleware.cors
import starlette.middleware.sessions
import starlette_login.backends
import starlette_login.login_manager
import starlette_login.middleware
import starlette_login.mixins
import starlette_login.utils
import starlette_login.decorator
import starlette.background
import pydantic
import sqlite3
import aiosqlite

import config
import model
import worker
import nlp
import utils
import search
import login










bg_tasks=None


@contextlib.asynccontextmanager
async def lifespan_event(app):
	async with anyio.create_task_group() as tg:
		global bg_tasks
		bg_tasks = tg
		print("Application starting up...")
		app.state.should_exit = False
		app.state.db_conn = await model.db_init(config.DB_PATH)
		print("database initialized")
		app.state.rebuild_queue = asyncio.Queue()
		tg.start_soon(worker.index_rebuilder, app)
		app.state.chunk_queue = asyncio.Queue()
		tg.start_soon(anyio.to_thread.run_sync, worker.note_chunker, app)
		tg.start_soon(worker.note_scanner, app)
		print("background worker initialized")

		yield

		print("Application shutting down...")
		app.state.should_exit = True
		await app.state.rebuild_queue.put(None)
		await app.state.chunk_queue.put((None, None))
		await anyio.sleep(0.5)
		await app.state.db_conn.commit()
		await app.state.db_conn.close()
		print("databse closed")
		tg.cancel_scope.cancel()


async def homepage(request):
	return starlette.responses.PlainTextResponse("This is notebook backend server")



async def get_note(request):
	notebookid = request.path_params['notebookid']
	noteid = request.path_params['noteid']

	# validate parameters
	try:
		assert notebookid!=0
		assert noteid!=0
	except:
		utils._error_json_resp(400, "invalid parameters")

	note = await model.Note.db_load(request.app.state.db_conn, notebookid, noteid)
	return utils._json_resp(200, "okay", content=dataclasses.asdict(note))


async def delete_note(request):
	notebookid = request.path_params['notebookid']
	noteid = request.path_params['noteid']

	# validate parameters
	try:
		assert notebookid!=0
		assert noteid!=0
	except:
		utils._error_json_resp(400, "invalid parameters")

	# remove from database
	await model.Note.db_delete(request.app.state.db_conn, notebookid, noteid)

	# remove from vector search index
	vs = await model.NotebookVectorStore.getVectorStore(notebookid, request.app.state.db_conn)
	vs.remove(noteid)
	await model.NotebookVectorStore.saveDB(request.app.state.db_conn, vs)

	return utils._json_resp(200, "okay")


async def update_note(request):
	notebookid = request.path_params['notebookid']
	noteid = request.path_params['noteid']

	# validate parameters
	try:
		assert notebookid!=0
		assert noteid!=0
	except:
		utils._error_json_resp(400, "invalid parameters")

	payload = await request.json()

	# validate post body
	class PostParams(pydantic.BaseModel):
		title: str = pydantic.Field(min_length=1)
		textcontent: str = pydantic.Field(min_length=1)
		noteid: int = pydantic.Field(gt=0)
		notebookid: int = pydantic.Field(gt=0)
	try:
		post_params = PostParams(**payload)
		assert post_params.noteid == noteid
		assert post_params.notebookid == notebookid
		assert post_params.title.strip() != ""
	except (pydantic.ValidationError, AssertionError) as e:
		return utils._error_json_resp(400, "invalid parameters", content={"error": e.errors()})

	# update to database
	await model.Note.db_update(request.app.state.db_conn, post_params.notebookid, post_params.noteid, post_params.title, post_params.textcontent)

	return utils._json_resp(200, "okay")


async def create_note(request):
	notebookid = request.path_params['notebookid']
	payload = await request.json()

	# validate parameters
	class PostParams(pydantic.BaseModel):
		title: str = pydantic.Field(min_length=1)
		textcontent: str = pydantic.Field(min_length=1)
	try:
		assert notebookid != 0
		post_params = PostParams(**payload)
		assert post_params.title.strip() != ""
	except (pydantic.ValidationError, AssertionError) as e:
		return utils._error_json_resp(400, "invalid parameters", content={"error": e.errors()})

	# update to database
	noteid = await model.Note.db_insert(request.app.state.db_conn, notebookid, post_params.title, post_params.textcontent)

	return utils._json_resp(200, "okay", content={
		'notebookid': notebookid,
		'noteid': noteid
	})



@utils.login_required
async def get_bookshelf(request):
	"""
	Get notebook table's rows at a certain page
	"""
	username = request.path_params['username']

	# validate parameters
	try:
		assert username != ""
		assert request.user.is_authenticated
		assert request.user.uid > 0
		assert request.user.username == username
	except Exception as e:
		return utils._error_json_resp(400, "invalid parameters", content=str(e))

	# query database
	notebooks = await model.Notebook.fetchUserNotebooks(request, request.user.uid)
	bookshelf = {
		"uid": request.user.uid,
		"username": request.user.username,
		"notebooks": [dataclasses.asdict(nb) for nb in notebooks],
	}
	return utils._json_resp(200, "okay", content=bookshelf)




@utils.login_required
async def get_notebook(request):
	"""
	Get notebook table's rows at a certain page
	"""
	notebookid = request.path_params['notebookid']
	raw_query_params = request.query_params._dict

	# validate parameters
	class Params(pydantic.BaseModel):
		page: typing.Optional[int] = pydantic.Field(1, ge=1)
		pagesize: typing.Optional[int] = pydantic.Field(50)
	try:
		assert notebookid!=0
		query_params = Params(**raw_query_params)
	except pydantic.ValidationError as e:
		return utils._error_json_resp(400, "invalid parameters", content=e.errors())
	except:
		return utils._error_json_resp(400, "invalid parameters")

	# query database
	offset = (query_params.page - 1) * query_params.pagesize
	tablename = "notebook_"+str(notebookid)
	cursor = await request.app.state.db_conn.cursor()
	await cursor.execute(f'''SELECT COUNT(*) FROM {tablename};''')
	total_n = await cursor.fetchone()
	total_n = total_n[0]
	await cursor.execute(f'''
		SELECT
			CAST(docid AS TEXT), title, content,
			CAST(strftime('%s', lastedit) AS INTEGER), meta
		FROM {tablename}
		ORDER BY lastedit DESC
		LIMIT {query_params.pagesize} OFFSET {offset};
	''')
	rows = await cursor.fetchall()
	await cursor.close()
	rows_size = len(rows)
	print(f"fetched {rows_size} rows from table#{notebookid}")

	notebook = {
		'notebookid': notebookid,
		'is_valid_cache': True,
		'page': query_params.page,
		'page_size': query_params.pagesize,
		'page_n': rows_size,
		'total_n': total_n,
		'notes': [{
			'notebookid': notebookid,
			'noteid': int(r[0]),
			'title': r[1],
			'textcontent': r[2],
			'lastedit': r[3],
		} for r in rows],
	}
	return utils._json_resp(200, "okay", content=notebook)


async def delete_notebook(request):
	"""
	Delete notebook's table
	"""
	notebookid = request.path_params['notebookid']

	# validate parameters
	try:
		assert notebookid!=0
	except:
		utils._error_json_resp(400, "invalid parameters")

	# query database
	tablename = "notebook_"+str(notebookid)
	cursor = await request.app.state.db_conn.cursor()
	await cursor.execute(f'''
		DROP TABLE IF EXISTS {tablename};
	''')
	await cursor.close()
	print("removed table#%s" % tablename)

	return utils._json_resp(200, "okay")


async def quicksearch_notebook(request):
	"""
	Perform FTS search on a notebook's notes
	"""
	notebookid = request.path_params['notebookid']
	raw_query_params = request.query_params._dict

	# validate parameters
	class Params(pydantic.BaseModel):
		kw: str = pydantic.Field(min_length=1, description="search keyword")
		k: typing.Optional[int] = pydantic.Field(5, gt=0, le=500, description="result size")
		ss: typing.Optional[int] = pydantic.Field(48, ge=-1, le=256, description="match snippet size")
		q: typing.Optional[bool] = pydantic.Field(True, description="result is quoted")
	try:
		assert notebookid!=0
		query_params = Params(**raw_query_params)
	except pydantic.ValidationError as e:
		return utils._error_json_resp(400, "invalid parameters", content={"error": e.errors()})
	except:
		utils._error_json_resp(400, "invalid parameters")

	result = await search.quick_search(request, notebookid, query_params.kw.strip(), k=query_params.k, snippet_size=query_params.ss, is_quoted=query_params.q)

	return utils._json_resp(200, "okay", content=result)




async def chunck_note(request):
	"""
	First split the content of a note into sentences,
	then group sentences by their semantic meanings into chunks.
	Finally get embeddings and character spans from each chuncks and save them
	to database alongside the note entry.
	"""
	notebookid = request.path_params['notebookid']
	noteid = request.path_params['noteid']

	note = await model.Note.db_load(request.app.state.db_conn, notebookid, noteid)
	rechunk = False
	if not note.dirty:
		b_emb, = await note.db_fetch_cols(request.app.state.db_conn, ['title_emb'])
		if not b_emb:
			rechunk = True
		else:
			emb = pickle.loads(b_emb)
			if len(emb)!=config.LLM_EMBED_D:
				rechunk = True
	else:
		rechunk = True
	if rechunk:
		chunks, chunk_spans, chunk_embs, title_emb = await note.make_chunks()
		await note.db_store_chunks(request.app.state.db_conn, title_emb, chunk_embs, chunk_spans)
		await note.db_store_cols(request.app.state.db_conn, ['dirty'], [False])
		request.app.state.db_conn.commit()

	return utils._json_resp(200, "okay", content=dataclasses.asdict(note))



async def vector_search(request):
	notebookid = request.path_params['notebookid']
	raw_query_params = request.query_params._dict

	# validate parameters
	class Params(pydantic.BaseModel):
		kw: str = pydantic.Field(min_length=1, description="search text")
		k: typing.Optional[int] = pydantic.Field(10, gt=0, le=100, description="result size")
		title: typing.Optional[bool] = pydantic.Field(True, description="search title")
		fts: typing.Optional[bool] = pydantic.Field(True, description="include fts result")
	try:
		assert notebookid!=0
		query_params = Params(**raw_query_params)
	except pydantic.ValidationError as e:
		return utils._error_json_resp(400, "invalid parameters", content={"error": e.errors()})
	except:
		utils._error_json_resp(400, "invalid parameters")

	result = await search.vsearch(request, notebookid, query_params.kw, k=query_params.k, search_title=query_params.title, search_fts=query_params.fts)
	if not result:
		return utils._error_json_resp(400, "llm server down")
	return utils._json_resp(200, "okay", content=result)




async def check_train(request):
	notebookid = request.path_params['notebookid']
	noteid = request.path_params['noteid']
	note = await model.Note.db_load(request.app.state.db_conn, notebookid=notebookid, noteid=noteid)
	if not note:
		return utils._error_json_resp(400, "note not found")
	await request.app.state.rebuild_queue.put(notebookid)  # trigger worker to check whether to rebuild faiss index
	# await request.app.state.chunk_queue.put((notebookid, noteid))
	return starlette.responses.JSONResponse({"code": 200, "status": "start bg task", "content": dataclasses.asdict(note)}, status_code=200)


login_manager_config = starlette_login.login_manager.Config(COOKIE_DURATION=datetime.timedelta(hours=1))
login_manager = starlette_login.login_manager.LoginManager(redirect_to='/login', secret_key='secret', config=login_manager_config)
login_manager.set_user_loader(model.User.getUserById)
middleware = [
	starlette.middleware.Middleware(starlette.middleware.cors.CORSMiddleware,
		allow_origins=["*", "http://192.168.1.220", "http://192.168.1.220:3000"],
		allow_credentials=True,
		allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
		allow_headers=["*"]),
	starlette.middleware.Middleware(starlette.middleware.sessions.SessionMiddleware, secret_key='secret', https_only=False, max_age=None),
	starlette.middleware.Middleware(
		starlette_login.middleware.AuthenticationMiddleware,
		backend=starlette_login.backends.SessionAuthBackend(login_manager),
		login_manager=login_manager,
		allow_websocket=False,
		excluded_dirs=['/static'],
	)
]
routes = [
	starlette.routing.Route('/', homepage),
	starlette.routing.Route("/api/login", login.login, methods=['GET', 'POST']),
	starlette.routing.Route("/api/logout", login.logout, methods=['GET', 'POST']),
	starlette.routing.Route("/api/register", login.register, methods=['POST']),
	starlette.routing.Route('/api/{username:str}/get', get_bookshelf),
	starlette.routing.Route('/api/note/{notebookid:int}/get', get_notebook),
	starlette.routing.Route('/api/note/{notebookid:int}/delete', delete_notebook),
	starlette.routing.Route('/api/note/{notebookid:int}/new', create_note, methods=['POST']),
	starlette.routing.Route('/api/note/{notebookid:int}/{noteid:int}/get', get_note),
	starlette.routing.Route('/api/note/{notebookid:int}/{noteid:int}/delete', delete_note),
	starlette.routing.Route('/api/note/{notebookid:int}/{noteid:int}/update', update_note, methods=['POST']),
	starlette.routing.Route('/api/note/{notebookid:int}/search', quicksearch_notebook),
	starlette.routing.Route('/api/note/{notebookid:int}/{noteid:int}/chunk', chunck_note),
	starlette.routing.Route('/api/note/{notebookid:int}/vsearch', vector_search),
	starlette.routing.Route('/api/note/{notebookid:int}/{noteid:int}/check', check_train),
	starlette.routing.Mount('/static', starlette.staticfiles.StaticFiles(directory="static")),
]
app = starlette.applications.Starlette(routes=routes, middleware=middleware, lifespan=lifespan_event)
app.state.login_manager = login_manager
app.state.config = config

if __name__ == "__main__":
	import uvicorn
	# Run the application programmatically
	uvicorn.run(app, host="0.0.0.0", port=8000)
