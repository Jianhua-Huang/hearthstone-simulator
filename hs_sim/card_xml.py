"""Read pinned CardDefs exports as data only; no behavior or pool inference."""

from pathlib import Path
import re
import xml.etree.ElementTree as ET

from .catalog import CardCatalog, CatalogError


TYPES = {3:'HERO',4:'MINION',5:'SPELL',6:'ENCHANTMENT',7:'WEAPON',10:'HERO_POWER',39:'LOCATION'}


def read_card_xml(path, *, expected_build):
    if type(expected_build) is not int or expected_build <= 0:
        raise CatalogError('A fixed positive source build is required')
    with Path(path).open('rb') as stream:
        return _read_xml_stream(stream,expected_build)


def _read_xml_stream(stream,expected_build):
    records=[]
    dbf_ids=set()
    context=ET.iterparse(stream,events=('start','end'))
    event,root=next(context)
    if root.tag!='CardDefs' or root.attrib.get('build')!=str(expected_build):
        raise CatalogError('CardDefs root/build differs from the frozen source receipt')
    for event,entity in context:
        if event!='end' or entity.tag!='Entity':continue
        cid=entity.attrib.get('CardID')
        try:dbf=int(entity.attrib['ID'])
        except (KeyError,ValueError) as exc:raise CatalogError('Invalid CardDefs DBF identity') from exc
        if dbf <= 0 or dbf in dbf_ids:raise CatalogError('Duplicate or invalid CardDefs DBF identity')
        dbf_ids.add(dbf)
        tags={};strings={};unmapped=[];card_refs=[]
        for tag in entity:
            if tag.tag!='Tag':
                unmapped.append({'tag':tag.tag,'attributes':dict(tag.attrib)})
                continue
            name=tag.attrib.get('name')
            if not name or not re.fullmatch('[A-Z][A-Z_0-9]*',name):
                enum_id=tag.attrib.get('enumID')
                if not enum_id or not enum_id.isdigit():
                    raise CatalogError('An unnamed CardDefs tag has no numeric identity')
                name=enum_id
                unmapped.append({'tag':tag.tag,'attributes':dict(tag.attrib),'normalized_key':name})
            kind=tag.attrib.get('type')
            if kind=='LocString':
                strings[name]={loc.tag:loc.text or '' for loc in tag}
            elif kind in ('Int','Card'):
                try:value=int(tag.attrib['value'])
                except (KeyError,ValueError) as exc:raise CatalogError('Invalid numeric CardDefs tag') from exc
                if name in tags:raise CatalogError('Duplicate numeric CardDefs tag')
                tags[name]=value
                if kind=='Card':card_refs.append({'tag':name,'dbf_id':value,'card_id':tag.attrib.get('cardID')})
            else:
                unmapped.append({'tag':tag.tag,'attributes':dict(tag.attrib),'text':tag.text or ''})
        def localized(name,locale):return strings.get(name,{}).get(locale,'')
        card_type=tags.get('CARDTYPE')
        records.append({
            'id':cid,'dbf_id':dbf,'name':localized('CARDNAME','zhCN'),
            'name_en':localized('CARDNAME','enUS'),'text':localized('CARDTEXT','zhCN'),
            'text_en':localized('CARDTEXT','enUS'),'cost':tags.get('COST'),
            'attack':tags.get('ATK'),'health':tags.get('HEALTH'),
            'type':TYPES.get(card_type,f'UNMAPPED_CARDTYPE_{card_type}'),
            'collectible':tags.get('COLLECTIBLE',0)==1,'tags':tags,
            'card_set_id':tags.get('CARD_SET'),'source_entity_version':entity.attrib.get('version'),
            'reference_tags':[],'power_keyword_tags':[],'related_dbf_ids':[],
            'xml_card_references':card_refs,'unmapped_xml_nodes':unmapped,
        })
        entity.clear()
    if not records:raise CatalogError('CardDefs contains no entity records')
    return CardCatalog(records)
