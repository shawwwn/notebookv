import json
import asyncio
import functools
import typing

import starlette.responses
import starlette.requests
import starlette_login.decorator


class PrettyJSONResponse(starlette.responses.Response):
	media_type = "application/json"

	def render(self, content) -> bytes:
		return json.dumps(
			content,
			ensure_ascii=False,
			allow_nan=False,
			indent=4,
			separators=(", ", ": "),
		).encode("utf-8")


def _json_resp(code, desc, content={}):
	return PrettyJSONResponse({"code": code, "status": desc, "content": content}, status_code=code)
	return starlette.responses.JSONResponse({"code": code, "status": desc, "content": content}, status_code=code)


def _error_json_resp(code, desc, content={}):
	return _json_resp(code, desc, content)




def login_required(func: typing.Callable) -> typing.Callable:
	idx = starlette_login.decorator.is_route_function(func, "request")

	if asyncio.iscoroutinefunction(func):

		@functools.wraps(func)
		async def async_wrapper(*args: typing.Any, **kwargs: typing.Any) -> starlette.responses.Response:
			request = kwargs.get("request", args[idx] if args else None)
			assert isinstance(request, starlette.requests.Request)

			login_manager = getattr(request.app.state, "login_manager", None)
			assert login_manager is not None, "LoginManager is not set"

			if request.method in login_manager.config.EXEMPT_METHODS:
				return await func(*args, **kwargs)  # pragma: no cover

			user = request.scope.get("user")
			if not user or getattr(user, "is_authenticated", False) is False:
				return PrettyJSONResponse({"code": 400, "status": "login required"}, status_code=400)
			else:
				return await func(*args, **kwargs)

		return async_wrapper
	else:

		@functools.wraps(func)
		def sync_wrapper(*args: typing.Any, **kwargs: typing.Any) -> starlette.responses.Response:
			request = kwargs.get("request", args[idx] if args else None)
			assert isinstance(request, starlette.requests.Request)

			login_manager = getattr(request.app.state, "login_manager", None)
			assert login_manager is not None, "LoginManager is not set"

			if request.method in login_manager.config.EXEMPT_METHODS:
				return func(*args, **kwargs)  # pragma: no cover

			user = request.scope.get("user")
			if not user or getattr(user, "is_authenticated", False) is False:
				return PrettyJSONResponse({"code": 400, "status": "login required"}, status_code=400)
			else:
				return func(*args, **kwargs)

		return sync_wrapper
