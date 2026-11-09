import re
from min_agent.memory.models import MemoryCandidate
RULES=[
 (r"(?:以后|今后|长期|一直)[^。！？；;]{2,90}","preference"),
 (r"(?:我偏好|我喜欢|我习惯|我通常使用).{2,60}","preference"),
 (r"(?:我的项目|目前项目).{2,70}(?:使用|采用|基于|技术栈).{2,70}","project"),
 (r"(?:我是|我的专业是|我目前就读于).{2,50}","profile")]
class MemoryExtractor:
 def extract(self,user_message:str)->list[MemoryCandidate]:
  text=" ".join(user_message.split()).strip()
  if not text or len(text)>1000:return []
  found={}
  for pattern,category in RULES:
   m=re.search(pattern,text)
   if m:
    content=m.group().strip(" ，。；;")
    key=category+":"+re.sub(r"[^\w\u4e00-\u9fff]+","_",content.lower())[:100]
    found[key]=MemoryCandidate(memory_key=key,content=content,category=category)
  return list(found.values())