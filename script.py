import asyncio, uuid  
from backend.app.database import async_session_maker  
from backend.app.models import FaceDetection, Photo  
from sqlalchemy import select  
async def main():  
    async with async_session_maker() as db:  
        res = await db.execute(select(FaceDetection))  
        dets = res.scalars().all()  
        if not dets: print('no dets'); return  
        c_id = dets[0].cluster_id  
        print(f'cluster_id: {c_id}')  
        det_res = await db.execute(select(FaceDetection).where(FaceDetection.cluster_id == c_id))  
        cluster_dets = det_res.scalars().all()  
        print(f'cluster_dets: {len(cluster_dets)}')  
        pids = list({d.photo_id for d in cluster_dets})  
        print(f'pids: {pids}')  
        pres = await db.execute(select(Photo).where(Photo.id.in_(pids)))  
        photos = pres.scalars().all()  
        print(f'photos: {len(photos)}')  
asyncio.run(main())  
