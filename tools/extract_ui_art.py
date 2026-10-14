"""Read-only extraction of local demo artwork; no game code or installation writes."""
import argparse, hashlib, json, warnings
from pathlib import Path
import UnityPy

UI_NAMES={'TheBox_Table','Jaina','Garrosh','Card_Back_PC_Master','Board_EndTurnButton','Card_Inhand_Generic','Hero_Power_Frame','Board_HeroTray'}
ROOT=Path(__file__).resolve().parents[1]
def extract(client):
    warnings.simplefilter('ignore');UnityPy.config.FALLBACK_UNITY_VERSION='6000.3.11f1'
    source=client/'Data'/'Win';dest=ROOT/'web_ui'/'static'/'assets';dest.mkdir(parents=True,exist_ok=True)
    manifest=UnityPy.load(str(source/'asset_manifest.unity3d'));cards={};catalog=None
    for obj in manifest.objects:
        if obj.type.name!='MonoBehaviour':continue
        d=obj.read_typetree()
        if d.get('m_Name')=='cards_map':cards=dict(zip(d['map']['keys'],d['map']['values']))
        if d.get('m_Name')=='base_assets_catalog':catalog=d
    by_guid={a['guid']:catalog['m_bundleNames'][a['bundleId']] for a in catalog['m_assets']}
    cache={};receipts=[];mapping={};missing=[]
    def load(bundle):
        if bundle not in cache:cache[bundle]=UnityPy.load(str(source/bundle))
        return cache[bundle]
    def save(texture,bundle,filename):
        image=texture.image
        image.thumbnail((1200,1200))
        image.save(dest/filename,'WEBP',quality=90)
        receipts.append({'file':filename,'bundle':bundle,'texture':texture.m_Name,'source_sha256':hashlib.sha256((source/bundle).read_bytes()).hexdigest(),'output_sha256':hashlib.sha256((dest/filename).read_bytes()).hexdigest()})
    for file in source.glob('essential_base_global-texture-*.unity3d'):
        for obj in load(file.name).objects:
            if obj.type.name=='Texture2D':
                tex=obj.read()
                if tex.m_Name in UI_NAMES:save(tex,file.name,tex.m_Name+'.webp')
    config=json.loads((ROOT/'examples/matches/constructed.json').read_text(encoding='utf8'))
    ids={c for d in config['decks'] for c in d['cards']};ids.update(('HERO_08','HERO_01','HERO_08bp','HERO_01bp','GAME_005','UNG_029'))
    for cid in sorted(ids):
        entry=cards.get(cid)
        if not entry:missing.append(cid);continue
        bundle=by_guid[entry.rsplit(':',1)[1]];env=load(bundle)
        game_objects={o.path_id:o.read().m_Name for o in env.objects if o.type.name=='GameObject'}
        portrait=None
        for obj in env.objects:
            if obj.type.name!='MonoBehaviour':continue
            d=obj.read_typetree()
            if game_objects.get(d.get('m_GameObject',{}).get('m_PathID'))==cid and d.get('m_PortraitTexturePath'):
                portrait=d['m_PortraitTexturePath'];break
        if not portrait:missing.append(cid);continue
        asset, guid=portrait.rsplit(':',1);texture_bundle=by_guid.get(guid)
        if not texture_bundle or not (source/texture_bundle).exists():missing.append(cid);continue
        expected=Path(asset).stem;found=False
        for obj in load(texture_bundle).objects:
            if obj.type.name=='Texture2D':
                tex=obj.read()
                if tex.m_Name==expected:
                    filename=cid+'.webp';save(tex,texture_bundle,filename);mapping[cid]=filename;found=True;break
        if not found:missing.append(cid)
    (dest/'cards.json').write_text(json.dumps(mapping,ensure_ascii=False,indent=2),encoding='utf8')
    (dest/'manifest.json').write_text(json.dumps({'client':str(client),'read_only':True,'purpose':'local experimental UI','assets':receipts,'missing_card_art':missing},ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'ui':sum(r['texture'] in UI_NAMES for r in receipts),'cards':len(mapping),'missing':missing},ensure_ascii=False))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--client',type=Path,default=Path(r'D:\游戏\Hearthstone'));extract(parser.parse_args().client)
