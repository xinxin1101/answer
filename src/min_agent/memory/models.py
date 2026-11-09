from typing import Literal
from pydantic import BaseModel, Field
Category = Literal["preference","profile","project","workflow","other"]
class MemoryItem(BaseModel):
 memory_id:str; user_id:str; memory_key:str; content:str; category:Category
 source:str="explicit_user_statement"; confidence:float=Field(default=.9,ge=0,le=1)
 status:str="active"; created_at:str; updated_at:str; expires_at:str|None=None
class MemoryCandidate(BaseModel):
 memory_key:str; content:str; category:Category; confidence:float=Field(default=.9,ge=0,le=1)
class MemorySearchResult(BaseModel):
 item:MemoryItem; score:float