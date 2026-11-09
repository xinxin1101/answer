from min_agent.memory.extractor import MemoryExtractor
from min_agent.memory.models import MemoryCandidate
from min_agent.memory.service import MemoryService
from min_agent.memory.store import MemoryStore
def test_extraction_is_conservative():
 e=MemoryExtractor();x=e.extract("以后我所有后端项目都优先使用 FastAPI。")
 assert x and "FastAPI" in x[0].content
 assert e.extract("今天帮我写一个 Python 脚本")==[]
def test_isolation_and_upsert(tmp_path):
 s=MemoryStore(str(tmp_path/"m.db"))
 a=MemoryCandidate(memory_key="preference:stack",content="Prefer Flask",category="preference")
 b=MemoryCandidate(memory_key="preference:stack",content="Prefer FastAPI",category="preference")
 x=s.upsert("a",a);y=s.upsert("a",b)
 assert x.memory_id==y.memory_id and y.content=="Prefer FastAPI" and not s.list_active("b")
def test_retrieval_and_archive(tmp_path):
 s=MemoryStore(str(tmp_path/"m.db"));m=MemoryService(s)
 m.remember_from_user_message("a","以后我所有后端项目都优先使用 FastAPI。")
 m.remember_from_user_message("a","我的项目目前使用 React 和 TypeScript。")
 r=s.search("a","FastAPI 后端开发")
 assert r and "FastAPI" in r[0].item.content
 assert s.archive("a",r[0].item.memory_id) and len(s.list_active("a"))==1