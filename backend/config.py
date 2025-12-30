#
# This is a configuration file
#
import os
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

SQLITE_TOKENIZER = "../libsimple/libsimple"
DB_PATH = os.path.join(SCRIPT_DIR, "db/database.db")
NPL_MODEL_NAME = "zh_core_web_sm"
# LLM_MODEL_NAME = "multi2"
# LLM_EMBED_D = 512
LLM_MODEL_NAME = "tarka150m"
LLM_EMBED_D = 768
LLM_API_URL = "http://192.168.1.220:8999/embedding"
LLM_HTTP_TIMEOUT = 300

FAISS_NLIST = 6
FAISS_NORMALIZE = True
FAISS_NPROBE = 3
