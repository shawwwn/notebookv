import requests

import httpx
import numpy as np
import nltk.tokenize.texttiling
import sklearn.metrics.pairwise

import config

nlp_model = None


def initNLP():
	global nlp_model
	if not nlp_model:
		print("load nlp model")
		import spacy
		nlp_model = spacy.load(config.NPL_MODEL_NAME)
		for p in nlp_model.pipe_names:
			nlp_model.remove_pipe(p)
		nlp_model.add_pipe('sentencizer')
	return nlp_model


def getEmbedLLM(sentences):
	payload = {
		"llm": config.LLM_MODEL_NAME,
		"contents": sentences,
	}
	try:
		response = requests.post(config.LLM_API_URL, json=payload)
	except Exception as err:
		print(f"failed to get embeddings: {err}")
		return None
	if response.status_code!=200:
		return None
	result = response.json()
	if result['status']!=200 or len(result['contents'])<=0:
		print(f"llm error: {result['message']}")
		return None
	assert len(result['contents'][0]) == config.LLM_EMBED_D
	return result['contents']


async def asyncGetEmbedLLM(sentences):
	async with httpx.AsyncClient(timeout=config.LLM_HTTP_TIMEOUT) as client:
		payload = {
			"llm": config.LLM_MODEL_NAME,
			"contents": sentences,
		}
		try:
			response = await client.post(config.LLM_API_URL, json=payload)
		except httpx.ConnectError as err:
			print(f"failed to get embeddings: {err}")
			return None
		if response.status_code != 200:
			return None
		result = response.json()
		if result['status']!=200 or len(result['contents'])<=0:
			print(f"llm error: {result['message']}")
			return None
		assert len(result['contents'][0]) == config.LLM_EMBED_D
		return result['contents']


def parseText(text):
	# parse text into spacy document object
	return nlp_model(text)


def splitSent(sent):
	# clean out text by removing dangling newline chars left by nlp model
	# start, end = sent.start_char, sent.end_char
	ss = []
	ss_spans = []
	pos = sent.start_char
	first = True
	for s in sent.text.split('\n'):
		if not first:
			pos += 1
		first = False
		if not s.strip():
			pos += len(s)
			continue
		sent_start = pos
		sent_end = pos+len(s)
		ss.append(s)
		ss_spans.append([sent_start, sent_end])
		pos = sent_end
	return ss, ss_spans


def splitDoc(doc):
	# split document text into sentences
	ss = []
	ss_spans = []
	for sent in doc.sents:
		st, st_spans = splitSent(sent)
		ss.extend(st)
		ss_spans.extend(st_spans)
	return ss, ss_spans


def makeChunks(sentences, spans, sent_embs):
	if len(sentences)==1:
		return sentences, spans

	gap_scores = sklearn.metrics.pairwise.cosine_similarity(sent_embs[:-1], sent_embs[1:])
	gap_scores = np.diag(gap_scores)  # TODO: rewrite similarity function, only calculate diagonal values
	# from sentence_transformers.utils import pairwise_cos_sim
	# gap_scores = model.similarity_pairwise(sent_embs[:-1], sent_embs[1:])
	tt = nltk.tokenize.texttiling.TextTilingTokenizer(smoothing_width=min(len(sentences)//8, 11)-1)
	smooth_scores = tt._smooth_scores(gap_scores)
	depth_scores = tt._depth_scores(smooth_scores)
	boundaries = tt._identify_boundaries(depth_scores)
	boundary_indices = (np.where(boundaries)[0]+1).tolist()

	chunks = []
	chunk_spans = []
	for start, end in zip([0]+boundary_indices, boundary_indices+[None]):
		# TODO: add ending punct to a sentence if it doesnt have already
		chunk_text = '\n'.join(sentences[start:end])
		sp = spans[start:end]
		chunk_span = [sp[0][0], sp[-1][1]]
		chunks.append(chunk_text)
		chunk_spans.append(chunk_span)
	return chunks, chunk_spans
