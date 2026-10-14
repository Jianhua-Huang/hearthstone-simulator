"""Read local Hearthstone DBF assets; never modify the client installation."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import warnings

import UnityPy
from UnityPy.exceptions import UnityVersionFallbackWarning

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ('enUS', 'deDE', 'esES', 'esMX', 'frFR', 'itIT', 'jaJP',
           'koKR', 'plPL', 'ptBR', 'ruRU', 'thTH', 'zhCN', 'zhTW')
TABLES = {'CARD', 'CARD_TAG', 'RELATED_CARDS', 'POWER_DEFINITION', 'CARD_RACE',
          'CLASS', 'CARD_SET', 'KEYWORD_TEXT', 'TRIGGER', 'FORMULA'}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def file_identity(path: Path) -> dict:
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest}


def version_info(path: Path) -> dict:
    if os.name != 'nt' or not path.is_file():
        return {}
    env = dict(os.environ, HS_EXTRACT_VERSION_FILE=str(path))
    command = ('$v = (Get-Item -LiteralPath $env:HS_EXTRACT_VERSION_FILE).VersionInfo; '
               '@{file=$v.FileVersion; product=$v.ProductVersion} | ConvertTo-Json -Compress')
    proc = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', command],
                          env=env, capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def localized(row: dict, field: str, locale: str) -> str:
    values = row.get(field, {}).get('m_locValues', [])
    index = LOCALES.index(locale)
    return values[index] if index < len(values) else ''


def validate_tables(tables: dict) -> None:
    """Refuse incompatible schemas rather than produce a misleading export."""
    for name in ('CARD', 'CARD_TAG'):
        if not isinstance(tables.get(name), list) or not tables[name]:
            raise ValueError(f'{name}: missing or empty table')
    card_ids = set()
    for row in tables['CARD']:
        if (not isinstance(row, dict) or type(row.get('m_ID')) is not int
                or not isinstance(row.get('m_noteMiniGuid'), str) or not row['m_noteMiniGuid']):
            raise ValueError('CARD: invalid identity fields')
        card_ids.add(row['m_ID'])
        for field in ('m_name', 'm_textInHand'):
            localized_field = row.get(field)
            values = localized_field.get('m_locValues') if isinstance(localized_field, dict) else None
            if (not isinstance(values, list) or len(values) != len(LOCALES)
                    or any(not isinstance(value, str) for value in values)):
                raise ValueError(f'CARD {row["m_ID"]}: incompatible locale schema in {field}')
    for row in tables['CARD_TAG']:
        if not isinstance(row, dict) or any(type(row.get(key)) is not int for key in
                                            ('m_cardId', 'm_tagId', 'm_tagValue')):
            raise ValueError('CARD_TAG: invalid numeric fields')
        if any(row.get(key) not in (0, 1) for key in ('m_isReferenceTag', 'm_isPowerKeywordTag')):
            raise ValueError('CARD_TAG: missing or invalid reference/keyword flags')
        if row['m_cardId'] not in card_ids:
            raise ValueError(f'CARD_TAG: orphan card ID {row["m_cardId"]}')


def normalize_cards(tables: dict, enums: dict, locale: str) -> list[dict]:
    tag_names = {value: name for name, value in enums['GAME_TAG'].items()}
    type_names = {value: name for name, value in enums.get('TAG_CARDTYPE', {}).items()}
    by_card = defaultdict(list)
    for row in tables['CARD_TAG']:
        by_card[row['m_cardId']].append(row)
    related = defaultdict(list)
    for row in tables.get('RELATED_CARDS', []):
        related[row['m_cardId']].append(row['m_relatedCardDatabaseId'])
    result = []
    seen_dbf, seen_ids = set(), set()
    for row in tables['CARD']:
        dbf_id, card_id = row['m_ID'], row['m_noteMiniGuid']
        if dbf_id in seen_dbf or card_id in seen_ids:
            raise ValueError(f'Duplicate card identity: {dbf_id} {card_id}')
        seen_dbf.add(dbf_id)
        seen_ids.add(card_id)
        tags, references, keywords = {}, [], []
        for entry in by_card[dbf_id]:
            key = tag_names.get(entry['m_tagId'], str(entry['m_tagId']))
            # Match EntityDef.LoadTagFromDBF_SetTags in the local client:
            # references enter their own channel, and power keywords also enter tags.
            if entry.get('m_isReferenceTag'):
                references.append({'tag': key, 'value': entry['m_tagValue']})
            if entry.get('m_isPowerKeywordTag'):
                keywords.append({'tag': key, 'value': entry['m_tagValue']})
            if not entry.get('m_isReferenceTag') or entry.get('m_isPowerKeywordTag'):
                if key in tags and tags[key] != entry['m_tagValue']:
                    raise ValueError(f'Conflicting tag on {card_id}: {key}')
                tags[key] = entry['m_tagValue']
        card = {
            'id': card_id, 'dbf_id': dbf_id,
            'name': localized(row, 'm_name', locale),
            'name_en': localized(row, 'm_name', 'enUS'),
            'text': localized(row, 'm_textInHand', locale),
            'text_en': localized(row, 'm_textInHand', 'enUS'),
            'cost': tags.get('COST'), 'attack': tags.get('ATK'), 'health': tags.get('HEALTH'),
            'type': type_names.get(tags.get('CARDTYPE'), str(tags['CARDTYPE']) if 'CARDTYPE' in tags else None),
            'collectible': bool(tags.get('COLLECTIBLE', 0)),
            'tags': tags, 'reference_tags': references, 'power_keyword_tags': keywords,
            'related_dbf_ids': related[dbf_id],
            'source_events': {key.removeprefix('m_'): val for key, val in row.items()
                              if key.endswith('Event')},
        }
        result.append(card)
    return sorted(result, key=lambda card: card['id'])


def main() -> None:
    parser = argparse.ArgumentParser(description='从本地炉石客户端只读提取卡牌数据；不包含服务器战斗脚本。')
    parser.add_argument('client', type=Path, help='炉石安装目录')
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'extracted')
    parser.add_argument('--enums', type=Path, default=ROOT / 'data' / 'schema' / 'enums.json')
    parser.add_argument('--locale', choices=LOCALES, default='zhCN')
    parser.add_argument('--unity-version', help='通常自动读取 UnityPlayer.dll，例如 6000.3.11f1')
    parser.add_argument('--raw', action='store_true', help='另外保存所选 DBF 表的全部原始记录（文件较大）')
    args = parser.parse_args()
    client, output = args.client.resolve(), args.output.resolve()
    if output == client or client in output.parents:
        parser.error('输出目录不能位于炉石安装目录中。')
    dbf = client / 'Data' / 'Win' / 'dbf.unity3d'
    if not dbf.is_file():
        parser.error(f'未找到 loose Unity bundle: {dbf}；此工具目前不解析 CASC。')
    if not args.enums.is_file():
        parser.error(f'缺少本地客户端枚举映射：{args.enums}')
    enums = json.loads(args.enums.read_text(encoding='utf-8-sig'))
    enum_source_path = args.enums.with_name(args.enums.stem + '.source.json')
    if not enum_source_path.is_file():
        parser.error(f'缺少枚举来源校验信息：{enum_source_path}；请先运行 tools/extract_enums.py。')
    enum_source = json.loads(enum_source_path.read_text(encoding='utf-8-sig'))
    assembly = client / 'Hearthstone_Data' / 'Managed' / 'Assembly-CSharp.dll'
    assembly_identity = file_identity(assembly)
    if assembly_identity['sha256'].lower() != enum_source['assembly_sha256'].lower():
        parser.error('当前客户端程序集与枚举版本不一致；请重新运行 tools/extract_enums.py。')
    player_info = version_info(client / 'UnityPlayer.dll')
    unity_version = args.unity_version or player_info.get('product', '').split(' ')[0]
    if not unity_version:
        parser.error('无法识别 Unity 版本，请提供 --unity-version。')
    UnityPy.config.FALLBACK_UNITY_VERSION = unity_version
    # Scrubbed bundles are expected: the fallback is recorded in manifest.json.
    warnings.filterwarnings('ignore', category=UnityVersionFallbackWarning)
    print(f'Reading {dbf.name} with Unity {unity_version}', flush=True)
    source_before = file_identity(dbf)
    env = UnityPy.load(str(dbf))
    tables, inventory = {}, []
    for obj in env.objects:
        if obj.type.name != 'MonoBehaviour':
            continue
        name = obj.peek_name()
        if name not in TABLES:
            inventory.append({'name': name, 'path_id': obj.path_id, 'parsed': False})
            continue
        tree = obj.read_typetree()
        rows = tree.get('Records', [])
        tables[name] = rows
        inventory.append({'name': name, 'path_id': obj.path_id, 'parsed': True,
                          'count': len(rows), 'fields': sorted({key for row in rows for key in row})})
        print(f'  {name}: {len(rows):,}', flush=True)
    validate_tables(tables)
    cards = normalize_cards(tables, enums, args.locale)
    source_after = file_identity(dbf)
    if source_before != source_after:
        raise RuntimeError('客户端数据在提取过程中发生变化；请在更新完成后重试。')
    if assembly_identity != file_identity(assembly):
        raise RuntimeError('客户端程序在提取过程中发生变化；请重新提取枚举和数据。')
    write_json(output / 'cards.json', cards)
    if args.raw:
        for name, rows in tables.items():
            write_json(output / 'raw' / f'{name}.json', rows)
    unknown = Counter(key for card in cards for key in card['tags'] if key.isdigit())
    summary = {
        'cards': len(cards), 'collectible_cards': sum(c['collectible'] for c in cards),
        'types': dict(Counter(c['type'] for c in cards)),
        'with_battlegrounds_tech_level': sum('TECH_LEVEL' in c['tags'] for c in cards),
        'unknown_regular_tag_ids': dict(unknown),
    }
    manifest = {
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'client': str(client), 'source': source_after,
        'client_executable_version': version_info(client / 'Hearthstone.exe'),
        'unity_player': player_info, 'unity_fallback': unity_version,
        'unitypy_version': UnityPy.__version__, 'locale': args.locale,
        'enum_source': file_identity(args.enums.resolve()),
        'client_assembly': assembly_identity,
        'summary': summary, 'tables': sorted(inventory, key=lambda t: t['name']),
        'limitations': [
            'Static local data only; no executable server card effects.',
            'Includes historical, token, cosmetic, test and other-mode records; not a current legal card pool.',
            'Server hotfixes and event activation are not applied.',
            'Missing tags stay null/absent; values are not inferred from card text.',
            'Enum mapping must be revalidated against Assembly-CSharp.dll after client upgrades.',
        ],
    }
    write_json(output / 'manifest.json', manifest)
    console_summary = dict(summary)
    console_summary['unknown_regular_tag_ids'] = len(unknown)
    print(json.dumps(console_summary, ensure_ascii=False, indent=2))
    print(f'Output: {output}')


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
