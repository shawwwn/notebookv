import asyncio
import gc
import contextlib
import psutil
import sentence_transformers

llm_profile = None  # singleton llm profile # TODO: use a semaphore to allow multiple concurrent LLMs
llm_lock = asyncio.Lock()
llm_profiles = {
	"default": "en",
	"en": {
		'repo': 'sentence-transformers/all-MiniLM-L6-v2',
		'ram': 100*1024*1024,
		'embedding_dimension': 384,
		'model_kwargs': {"dtype": "float16"},
	},
	"multi": {
		'repo': 'sentence-transformers/multi-qa-distilbert-cos-v1',
		'ram': 300*1024*1024,
		'embedding_dimension': 768,
		'model_kwargs': {"dtype": "float16"},
	},
	"multi2": {
		'repo': 'sentence-transformers/distiluse-base-multilingual-cased-v1',
		'ram': 600*1024*1024,
		'embedding_dimension': 512,
		'model_kwargs': {"dtype": "float16"},
	},
	"tarka150m": {
		'repo': 'Tarka-AIR/Tarka-Embedding-150M-V1',
		'ram': 800*1024*1024,
		'embedding_dimension': 768,
		'trust_remote_code': True,
	},
}


def select_llm_profile(name):
	"""
	Return a LLM profile from given @name,
	but check whether the machine has enough ram to run the LLM first
	"""
	name = llm_profiles[name] if name == "default" else name
	profile = llm_profiles.get(name)
	if not profile:
		print("error: llm profile not found")
		return None

	profile['instance'] = None if 'instance' not in profile else profile['instance']
	if not profile['instance']:
		avail_memory = psutil.virtual_memory().available
		if avail_memory < profile['ram']:
			print("error: not enough memory to launch a new llm")
			return None

	return profile


async def launch_llm(profile):
	"""
	Launch a LLM instance if not launched
	Return an existing instance if already running and refresh its idle counter
	"""
	global llm_profile

	# llm already launched
	if llm_profile and llm_profile['instance']:
		if profile == llm_profile:
			return llm_profile['instance']
		else:
			print("info: close llm %s" % llm_profile['repo'])
			llm_profile['instance'] = None  # close other LLMs first
			gc.collect()

	# launch llm
	instance = None if 'instance' not in profile else profile['instance']
	if not instance:
		print("info: launch llm %s ..." % profile['repo'])
		try:
			model_kwargs = profile['model_kwargs'] if 'model_kwargs' in profile else None
			instance = sentence_transformers.SentenceTransformer(profile['repo'], model_kwargs=model_kwargs)
		except Exception as err:
			print(err)
			print("error: launch llm failed")
			return None

	profile['instance'] = instance
	profile['idle'] = 0
	llm_profile = profile
	return instance


@contextlib.asynccontextmanager
async def hold_llm(which_llm):
	"""
	Hold the resource for a LLM to be launched
	"""
	try:
		await asyncio.wait_for(llm_lock.acquire(), timeout=10)
		profile = select_llm_profile(which_llm)
		if not profile:
			raise
		instance = await launch_llm(profile)
		if not instance:
			raise
		yield instance
	except asyncio.TimeoutError:
		print("warn: hold_llm() timed out")
		yield None
	except Exception as err:
		print(err)
		yield None
	finally:
		print("finally")
		if llm_lock.locked():
			llm_lock.release()
