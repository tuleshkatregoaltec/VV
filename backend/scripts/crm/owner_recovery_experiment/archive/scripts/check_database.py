import asyncio,json,sys
from pathlib import Path
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT/'frozen_backend'))
from app.config import settings
import asyncpg
async def main():
 before=json.loads((ROOT/'database-before.json').read_text());after={};diff={}
 conn=await asyncpg.connect(str(settings.POSTGRES_URL).replace('postgresql+asyncpg://','postgresql://'))
 try:
  async with conn.transaction(readonly=True,isolation='repeatable_read'):
   for table in before:
    rows=await conn.fetch(f'SELECT id,md5(to_jsonb(t)::text) digest FROM {table} t WHERE organization_id=$1 ORDER BY id','f195cfaf-6e25-4ff0-8bbf-ca84509ae927')
    now={str(r['id']):r['digest'] for r in rows};after[table]=now
    diff[table]={'before_rows':len(before[table]),'after_rows':len(now),'added':len(now.keys()-before[table].keys()),'removed':len(before[table].keys()-now.keys()),'changed':sum(now[k]!=before[table][k] for k in now.keys()&before[table].keys())}
 finally:await conn.close()
 (ROOT/'database-after.json').write_text(json.dumps(after,sort_keys=True))
 result={'unchanged':before==after,'tables':diff};(ROOT/'database-unchanged-check.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
asyncio.run(main())
