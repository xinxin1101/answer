import sqlite3,uuid,re
from contextlib import contextmanager
from pathlib import Path
from min_agent.memory.models import MemoryCandidate,MemoryItem,MemorySearchResult
class MemoryStore:
 def __init__(self,database_path:str):
  self.path=database_path
  if database_path!=":memory:":Path(database_path).parent.mkdir(parents=True,exist_ok=True)
  self.mem=sqlite3.connect(":memory:") if database_path==":memory:" else None
  with self.db() as c:
   c.execute("""CREATE TABLE IF NOT EXISTS memories(memory_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,memory_key TEXT NOT NULL,content TEXT NOT NULL,category TEXT NOT NULL,source TEXT NOT NULL,confidence REAL NOT NULL,status TEXT NOT NULL DEFAULT 'active',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,expires_at TEXT,UNIQUE(user_id,memory_key))""")
   c.execute("CREATE INDEX IF NOT EXISTS idx_mem_owner ON memories(user_id,status)")
   c.commit()
 @contextmanager
 def db(self):
  c=self.mem or sqlite3.connect(self.path,timeout=5); c.row_factory=sqlite3.Row
  try:yield c
  finally:
   if self.mem is None:c.close()
 @staticmethod
 def owner(uid):
  if not uid.strip():raise ValueError("user_id must not be blank")
  return uid.strip()
 @staticmethod
 def item(row):return MemoryItem(**dict(row))
 def upsert(self,uid:str,x:MemoryCandidate)->MemoryItem:
  uid=self.owner(uid)
  with self.db() as c:
   row=c.execute("SELECT * FROM memories WHERE user_id=? AND memory_key=?",(uid,x.memory_key)).fetchone()
   mid=row["memory_id"] if row else str(uuid.uuid4())
   if row:c.execute("UPDATE memories SET content=?,category=?,confidence=?,status='active',updated_at=CURRENT_TIMESTAMP,expires_at=NULL WHERE user_id=? AND memory_key=?",(x.content,x.category,x.confidence,uid,x.memory_key))
   else:c.execute("INSERT INTO memories(memory_id,user_id,memory_key,content,category,source,confidence) VALUES(?,?,?,?,?,?,?)",(mid,uid,x.memory_key,x.content,x.category,"explicit_user_statement",x.confidence))
   c.commit()
   return self.item(c.execute("SELECT * FROM memories WHERE memory_id=?",(mid,)).fetchone())
 def list_active(self,uid):
  with self.db() as c:return [self.item(r) for r in c.execute("SELECT * FROM memories WHERE user_id=? AND status='active' ORDER BY updated_at DESC",(self.owner(uid),)).fetchall()]
 @staticmethod
 def terms(s):return set(re.findall(r"[a-zA-Z0-9_]{2,}|[\u4e00-\u9fff]{2,}",s.lower()))
 def search(self,uid,query,limit=5):
  if limit<1:raise ValueError("limit must be at least 1")
  q=self.terms(query); ranked=[]
  for item in self.list_active(uid):
   t=self.terms(item.content+" "+item.category); n=len(q&t)
   if n:ranked.append(MemorySearchResult(item=item,score=.75*n/max(1,len(q))+.25*n/max(1,len(t))))
  return sorted(ranked,key=lambda r:-r.score)[:limit]
 def archive(self,uid,mid):
  with self.db() as c:
   cur=c.execute("UPDATE memories SET status='archived',updated_at=CURRENT_TIMESTAMP WHERE user_id=? AND memory_id=? AND status='active'",(self.owner(uid),mid));c.commit();return cur.rowcount>0