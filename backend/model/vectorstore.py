import copy
import pickle
import datetime

import faiss
import numpy as np

import config


class VectorStoreBase():
	def __init__(self):
		self._next_emb_id = 1
		self.last_rebuild = datetime.datetime.min
		print("vs base init")

	def gen_emb_ids(self, n=1):
		"""
		Generate monotonic increasing embedding ids for faiss index
		"""
		emb_ids = np.arange(self._next_emb_id, self._next_emb_id+n, dtype='int64')
		self._next_emb_id += n
		return emb_ids

	def add(self, *args, **kwargs):
		print("vs base add")
		pass

	def train(self, *args, **kwargs):
		print("vs base train")
		pass

	def search(self, *args, **kwargs):
		print("vs base search")
		pass

	@classmethod
	def _conv_nparray(cls, arr):
		"""
		Convert to np.array(dtype=float32) for faiss indexing
		"""
		if not isinstance(arr, np.ndarray):
			arr = np.array(arr, dtype=np.float32)
		else:
			arr = arr.astype(np.float32)
		return arr

	@classmethod
	def _get_invlists(cls, faiss_index):
		"""
		Print internal ids of a faiss index
		"""
		idx = faiss.extract_index_ivf(faiss_index)
		invlists = idx.invlists
		all_ids = []
		for listno in range(idx.nlist):
			ls = invlists.list_size(listno)
			if ls == 0:
				continue
			all_ids.append(
				faiss.rev_swig_ptr(invlists.get_ids(listno), ls).copy()
			)
		return all_ids


class NotebookVectorStore(VectorStoreBase):
	active_vs = None  # TODO: multiple instances
	emb_id_map: dict = {}  # key: int -> value: Tuple(noteid: int, List[start: int, end: int])
	noteid_map: dict = {}  # key: int -> value: List[embedding_id: int])

	@classmethod
	async def getVectorStore(cls, notebookid: int, db_conn):
		"""
		Maintain only one vectorstore instance for each notebookid
		"""
		if cls.active_vs:
			if cls.active_vs.notebookid==notebookid:
				print(f"vectorstore#{notebookid}: use cached")
				return cls.active_vs

			# save previous instance
			await cls.saveDB(db_conn, cls.active_vs)

		# load/create a new instance
		vs = await cls.loadDB(db_conn, notebookid=notebookid)
		if not vs:
			print(f"vectorstore#{notebookid}: create new")
			vs = NotebookVectorStore(notebookid=notebookid)

		cls.active_vs = vs
		return vs

	def __init__(self, notebookid, emb_d=config.LLM_EMBED_D, nlist=config.FAISS_NLIST, nprobe=config.FAISS_NPROBE, normalize=config.FAISS_NORMALIZE):
		assert notebookid!=""
		super().__init__()
		self.emb_d = emb_d  # embedding dimension
		self.normalize = normalize
		self.notebookid = notebookid
		self.tablename = "notebook_" + str(notebookid)
		self.nlist = nlist
		self.nprobe = nprobe

		self._next_emb_id = 1
		self._next_emb_id_title = 1
		self.emb_count = 0
		self.modifies = 0

		self.clear()

	def clear(self):
		self.index = faiss.index_factory(self.emb_d, f"IVF{self.nlist},Flat", faiss.METRIC_INNER_PRODUCT)
		self.index.set_direct_map_type(faiss.DirectMap.Hashtable)
		self.index.nprobe = self.nprobe
		self.index_title = faiss.index_factory(self.emb_d, f"IDMap,Flat", faiss.METRIC_INNER_PRODUCT)
		self.emb_id_map = {}  # embedding id --> [note id, [span]]
		self.noteid_map = {}  # note id --> [embedding ids, ...]
		self.emb_id_map_title = {}  # embedding id --> note id
		self.noteid_map_title = {}  # note id --> embedding id

	def gen_emb_ids_title(self, n=1):
		"""
		Generate monotonic increasing embedding ids for faiss index
		"""
		emb_ids_title = np.arange(self._next_emb_id_title, self._next_emb_id_title+n, dtype='int64')
		self._next_emb_id_title += n
		return emb_ids_title

	def remove(self, noteid: int):
		"""
		Remove all embeddings and their mappings related to
		a note from faiss index.
		"""
		assert isinstance(noteid, int)
		assert self.index is not None
		if not self.index.is_trained:
			return

		if noteid in self.noteid_map:
			emb_ids = self.noteid_map[noteid]
			c = self.index.remove_ids(self._conv_nparray(emb_ids))
			self.modifies += c
			print(f"removed {c} embeddings")
			self.emb_count -= c
			for eid in emb_ids:
				eid = int(eid)
				del self.emb_id_map[eid]
		if noteid in self.noteid_map_title:
			eid = self.noteid_map_title[noteid]
			self.index_title.remove_ids(self._conv_nparray([eid]))
			del self.emb_id_map_title[eid]

	def add(self, noteid: int, chunk_embs, chunk_spans, title_emb) -> (list[np.int64], np.int64):
		"""
		Add a note's chunk embeddings to faiss index.
		For each embedding id, set up a mapping to its span and its note id.
		Return newly added embedding ids.
		"""
		assert isinstance(noteid, int)
		assert len(chunk_spans)==len(chunk_embs)
		assert self.index is not None
		assert self.index.is_trained is True

		# clear old mappings
		if noteid in self.noteid_map:
			old_emb_ids = self.noteid_map[noteid]
			c = self.index.remove_ids(self._conv_nparray(old_emb_ids))
			self.modifies += c
			print(f"removed {c} old embeddings")
			self.emb_count -= c
			for eid in old_emb_ids:
				eid = int(eid)
				del self.emb_id_map[eid]
		if noteid in self.noteid_map_title:
			old_eid = self.noteid_map_title[noteid]
			self.index_title.remove_ids(self._conv_nparray([old_eid]))
			del self.emb_id_map_title[old_eid]

		# setup new mappings from note id to embedding ids
		emb_ids = self.gen_emb_ids(len(chunk_embs))
		self.noteid_map[noteid] = emb_ids
		title_emb_ids = self.gen_emb_ids_title(1)
		self.noteid_map_title[noteid] = title_emb_ids[0]

		# setup new mappings from embedding id to span
		for i, eid in enumerate(emb_ids):
			eid = int(eid)
			self.emb_id_map[eid] = (noteid, chunk_spans[i])
		self.emb_id_map_title[title_emb_ids[0]] = noteid

		# add to faiss index
		chunk_embs = self._conv_nparray(chunk_embs)
		self.normalize and faiss.normalize_L2(chunk_embs)
		self.index.add_with_ids(chunk_embs, emb_ids)
		c = len(chunk_embs)
		self.modifies += c
		print(f"added {c} embeddings")
		self.emb_count += c

		title_emb = self._conv_nparray([title_emb])
		self.normalize and faiss.normalize_L2(title_emb)
		self.index_title.add_with_ids(title_emb, title_emb_ids)

		return emb_ids, title_emb_ids[0]

	def train(self, embs):
		"""
		Train faiss index. Run before add.
		@embs: all chunk embeddings in a notebook
		"""
		embs = self._conv_nparray(embs)
		print(f"train {len(embs)} embeddings ...")
		self.normalize and faiss.normalize_L2(embs)
		self.index.train(embs)
		print("training done")

	def search_title(self, query_emb, k=5):
		query_emb = self._conv_nparray(query_emb)
		self.normalize and faiss.normalize_L2(query_emb)
		D, indices = self.index_title.search(query_emb, k)
		return D, indices

	def search(self, query_emb, k=5):
		"""
		Search faiss index
		"""
		query_emb = self._conv_nparray(query_emb)
		self.normalize and faiss.normalize_L2(query_emb)
		D, indices = self.index.search(query_emb, k)
		return D, indices

	@classmethod
	async def saveDB(cls, db_conn, instance, notebookid=None):
		"""
		Save a NotebookVectorStore instance to database
		"""
		assert isinstance(instance, cls) or instance is None
		if not notebookid:
			notebookid = instance.notebookid

		b_obj = None
		if instance is not None:
			ins = copy.copy(instance)
			ins.index = faiss.serialize_index(ins.index)
			ins.index_title = faiss.serialize_index(ins.index_title)
			b_obj = pickle.dumps(ins)

		cursor = await db_conn.cursor()
		await cursor.execute(f'''
			UPDATE Notebooks
			SET vectorstore = ?
			WHERE nbid = {notebookid};
		''', (b_obj,))
		print(f"vectorstore#{notebookid}: save to db")
		await cursor.close()
		await db_conn.commit()

	@classmethod
	async def loadDB(cls, db_conn, notebookid: int):
		"""
		Load a NotebookVectorStore instance from database
		"""
		assert isinstance(notebookid, int)
		cursor = await db_conn.cursor()
		await cursor.execute(f'''
			SELECT
				vectorstore
			FROM Notebooks
			WHERE nbid = {notebookid};
		''')
		b_obj = await cursor.fetchone()
		await cursor.close()
		if len(b_obj)==0 or not b_obj[0]:
			print(f"vectorstore#{notebookid}: not found in db")
			return None

		instance = pickle.loads(b_obj[0])
		assert isinstance(instance, cls)
		assert instance.emb_d == config.LLM_EMBED_D
		assert instance.notebookid == notebookid
		instance.index = faiss.deserialize_index(instance.index)
		instance.index_title = faiss.deserialize_index(instance.index_title)
		print(f"vectorstore#{notebookid}: load from db")
		return instance





