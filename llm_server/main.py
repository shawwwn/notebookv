import asyncio
import starlette
import starlette.routing
import starlette.responses
import starlette.applications
import starlette.config
import starlette.datastructures
import starlette.staticfiles
# config = starlette.config.Config(".env")
# DEBUG = config('DEBUG', cast=bool, default=False)
# PASSWORD = config('PASSWORD', cast=starlette.datastructures.Secret, default="")

import llm


async def homepage(request):
	return starlette.responses.PlainTextResponse("This is a barebone LLM Server")


async def get_embeddings(request):
	user_data = None
	print(request.headers)
	sentences = []
	which_llm = 'default'
	result_json = {
		'status': 200,
		'message': "okay",
		'contents': sentences,
	}

	# parse payload
	try:
		user_data = await request.json()
		which_llm = which_llm if 'llm' not in user_data else user_data['llm']
		sentences = user_data['contents']
	except:
		result_json['status'] = 400
		result_json['message'] = 'invalid json'
		return starlette.responses.JSONResponse(result_json)

	# invoke llm
	async with llm.hold_llm(which_llm) as model:
		print("debug: llm = %r" % model)
		if not model:
			result_json['status'] = 400
			result_json['message'] = 'llm is not available'
			return starlette.responses.JSONResponse(result_json)

		try:
			embeddings = model.encode(sentences)
			print("debug: embeddings shape: %s" % (embeddings.shape,))
			result_json['contents'] = embeddings.tolist()
			# similarities = model.similarity(embeddings, embeddings)
			# print(similarities)
			# from sklearn.metrics.pairwise import cosine_similarity
			# print(cosine_similarity([embeddings[0]], embeddings[1:]))

		except Exception as err:
			print(err)
			result_json['status'] = 400
			result_json['message'] = 'unable to encode sentence'
			return starlette.responses.JSONResponse(result_json)

	# return embeddings
	return starlette.responses.JSONResponse(result_json)


routes = [
	starlette.routing.Route('/', homepage),
	starlette.routing.Route('/embedding', get_embeddings, methods=["POST"]),
	starlette.routing.Mount('/static', starlette.staticfiles.StaticFiles(directory="static")),
]
app = starlette.applications.Starlette(routes=routes)
