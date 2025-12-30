import urllib.parse
import typing
import json

import pydantic
import starlette_login.backends
import starlette_login.login_manager
import starlette_login.middleware
import starlette_login.mixins
import starlette_login.utils
import starlette_login.decorator
import starlette.responses

import utils
import model



async def login(request):
	"""
	User login
	"""
	if request.method == "POST":
		if request.user.is_authenticated:
			print("attempt to logout as %s(%s)" % (request.user.username, request.user.uid))
			model.user.user_pool.pop(request.user.uid)
			model.user.user_pool.pop(request.user.username)
			await starlette_login.utils.logout_user(request)
			# return utils._error_json_resp(400, "already logged in",
			# 	content={"uid": request.user.uid, "username": request.user.username})

		body = (await request.body()).decode()
		raw_form = dict(urllib.parse.parse_qsl(body))

		# validate post body
		class PostParams(pydantic.BaseModel):
			username: str = pydantic.Field(min_length=1)
			password: str = pydantic.Field(min_length=1)
			rememberme: typing.Optional[bool] = pydantic.Field(False)
		try:
			post_params = PostParams(**raw_form)
		except pydantic.ValidationError as e:
			return utils._error_json_resp(400, "invalid parameters", content=e.errors())

		print("attempt to login as %s with password=%s" % (post_params.username, post_params.password))
		user = await model.User.getUserByName(request, post_params.username)
		if not user:
			request.session.clear()
			return utils._error_json_resp(400, "no such user")
		else:
			if user.password != post_params.password:
				request.session.clear()
				return utils._error_json_resp(400, "incorrect password")

		await starlette_login.utils.login_user(request, user, remember=post_params.rememberme, duration=None)
		await user.update_lastlogin(request)
		return utils._json_resp(200, "logged in", content={
			"uid": user.uid,
			"username": user.username,
		})

	else:
		LOGIN_PAGE = f"""
			<form method="POST">
			<label>username <input name="username" value="admin"></label>
			<label>Password <input name="password" type="password" value="1234"></label>
			<label class="checkbox"><input type="checkbox" name="rememberme" value="1"> Remember me</label>
			<button type="submit">Login</button>
			</form>
			<form action="/api/logout" method="POST">
			<button type="submit">Logout</button>
			</form>

			<form action="/api/register" method="POST">
			<label>username <input name="username"></label>
			<label>Password <input name="password" type="password"></label>
			<button type="submit">Register</button>
			</form>
		"""
		if not isinstance(request.user, starlette_login.mixins.AnonymousUser):
			LOGIN_PAGE += f'''
				<p>uid: {request.user.uid}</p>
				<p>username: {request.user.username}</p>
				<p>password: {request.user.password}</p>
				<p>lastlogin: {request.user.lastlogin}</p>
				<p>since: {request.user.since}</p>
				<p>isadmin: {request.user.isadmin}</p>
			'''
		else:
			LOGIN_PAGE += '<p>AnonymousUser</p>'
		data = request.session
		text = '<p>'+json.dumps(data, indent=4)+'</p>'
		if request.user.is_authenticated:
			text += '<p>Is authenticated!</p>'
			text += f'<p>{request.user}</p>'
		return starlette.responses.HTMLResponse(LOGIN_PAGE+text)


async def logout(request):
	"""
	Current user logout
	"""
	if not request.user.is_authenticated:
		return utils._error_json_resp(400, "not logged in")

	user = request.user
	print("attempt to logout as %s(%s)" % (user.username, user.uid))
	await starlette_login.utils.logout_user(request)
	model.user.user_pool.pop(user.uid)
	model.user.user_pool.pop(user.username)
	return utils._json_resp(200, "logged out", content={
		"uid": user.uid,
		"username": user.username,
	})


async def register(request):
	"""
	New user register
	"""
	body = (await request.body()).decode()
	raw_form = dict(urllib.parse.parse_qsl(body))

	# validate post body
	class PostParams(pydantic.BaseModel):
		username: str = pydantic.Field(min_length=1)
		password: str = pydantic.Field(min_length=1)
	try:
		post_params = PostParams(**raw_form)
	except pydantic.ValidationError as e:
		return utils._error_json_resp(400, "invalid parameters", content={"error": e.errors()})

	print("attempt to register as '%s' with password '%s'" % (post_params.username, post_params.password))
	uid = await model.User.createUser(request, post_params.username, post_params.password)
	if not uid:
		return utils._error_json_resp(400, "unable to create user")
	print(f"suscessfully registered {post_params.username}(uid={uid})")

	# create a notebook for user
	await model.Notebook.createNotebook(request, uid)

	return utils._json_resp(200, "registered", content={
		"uid": uid,
		"username": post_params.username,
	})
