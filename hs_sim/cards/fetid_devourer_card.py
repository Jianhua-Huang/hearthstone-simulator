"""Fetid replaces its held face with the last played card's complete Rune set."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.effects import ChoiceOption, DestroyBatch, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import UpgradeHandCard
from hs_sim.engine.model import CardDefinition, CardType, HandProgressSpec, TargetMode, TargetSpec, Zone
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import MinionReference, live_minion
from hs_sim.engine.spell_sequences import DrawWithCostReduction
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.targeting import target_choices
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'BE_781'
PREFIX = 'cards.fetid_devourer.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/fetid-devourer-v1.json'
BATCH_HASH = '2df7f7de06d994f00a6a0cba43a41a57eacb7af50877c72826c1c0ce9fecb4f6'
# All nineteen actual printed destinations. No cumulative or rolling Rune state.
FORMS = {
    (1, 1, 1): 'BE_781t1', (1, 0, 0): 'BE_781t2', (2, 0, 0): 'BE_781t3',
    (3, 0, 0): 'BE_781t4', (0, 1, 0): 'BE_781t5', (0, 2, 0): 'BE_781t6',
    (0, 3, 0): 'BE_781t7', (0, 0, 1): 'BE_781t8', (0, 0, 2): 'BE_781t9',
    (0, 0, 3): 'BE_781t10', (1, 1, 0): 'BE_781t11', (1, 0, 1): 'BE_781t12',
    (2, 1, 0): 'BE_781t13', (2, 0, 1): 'BE_781t14', (1, 2, 0): 'BE_781t15',
    (1, 0, 2): 'BE_781t16', (0, 1, 1): 'BE_781t17', (0, 2, 1): 'BE_781t18',
    (0, 1, 2): 'BE_781t19',
}
COUNTS = {cid: runes for runes, cid in FORMS.items()}
PROGRESS = HandProgressSpec('event', on_complete=PREFIX+'shift', repeat=True,
    event='card_played', condition_id=PREFIX+'rune_play')
DOMAIN = TargetSpec(TargetMode.IF_AVAILABLE, zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='enemy')


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            set(x['record']['id'] for x in data['dependencies']) != set(COUNTS) or
            len(data['dependencies']) != 19 or any(data[k] for k in ('existing_dependencies', 'evidence_only', 'skipped')) or
            data['official_faces_verified'] != 40 or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards']+data['dependencies'])):
        raise TargetValidationError('Fetid requires its original root, nineteen complete forms and forty primary faces')
    return data


def original_play(c):
    e = c.event
    if e is None or e.kind != 'card_played':
        raise ResolutionError('Fetid requires its actual completed hand play')
    record = play_record(c.state, dict(e.data).get('play_id'))
    if (not record.completed or (record.source_id, record.player_id) != (e.source_id, e.player_id) or
            not record.action <= e.action <= c.state.action_number):
        raise ResolutionError('Fetid changed its original completed Rune play')
    return record


def destination(c):
    record = original_play(c)
    if record.player_id != c.player_id: return None
    meta = record.played_face.metadata
    if meta is None: raise UnsupportedDefinitionError('Fetid original played Rune metadata is unknown')
    if meta.runes is None: return None
    runes = (meta.runes.blood, meta.runes.frost, meta.runes.unholy)
    if not any(runes): return None
    if runes not in FORMS: raise UnsupportedDefinitionError('Fetid has no reviewed face for the original Rune set')
    return FORMS[runes]


def register_fetid_devourer_card(registry):
    def shift(c):
        if (c.trigger is None or c.trigger.kind != 'hand_progress' or c.trigger.hand_progress != PROGRESS or
                c.source.zone != Zone.HAND or c.source.card_id not in (CARD, *COUNTS)):
            raise ResolutionError('Fetid lost its original held listener and physical face')
        selected = destination(c)
        return () if selected is None or selected == c.source.card_id else (
            UpgradeHandCard(CardReference.capture(c.source), selected, c.source_id),)

    def body(c):
        if c.battlecry is None or c.battlecry.payload.card_id not in COUNTS:
            raise ResolutionError('Fetid requires its original actual Battlecry form')
        blood, frost, unholy = COUNTS[c.battlecry.payload.card_id]
        work = []
        if blood:
            domain = replace(registry.card(c.battlecry.payload.card_id), kind=c.source.kind, targeting=DOMAIN)
            actor = replace(c.source, controller=c.player_id)
            ids = tuple(i for i in target_choices(c.state, registry, actor, domain) if i is not None)
            options = tuple(ChoiceOption(json.dumps(asdict(MinionReference.capture(c.state.entities[i])), sort_keys=True),
                registry.card(c.state.entities[i].card_id).name, card_id=c.state.entities[i].card_id, entity_id=i) for i in ids)
            count = min(blood, len(options))
            if count:
                work.append(RequestChoice(c.player_id, options, c.source_id, prompt='选择要消灭的敌方随从',
                    min_count=count, max_count=count, on_select=PREFIX+'destroy_selected', targeting=DOMAIN))
        work.extend(DrawWithCostReduction(c.player_id, 3, c.source_id) for _ in range(frost))
        if unholy:
            summon = SummonFromPool(c.player_id, 'constructed.cards', PoolQuery(kinds=(CardType.MINION,),
                min_cost=3*unholy, max_cost=3*unholy, collectible=True), source_id=c.source_id, cause=SummonCause.capture(c))
            work.extend((summon, summon))
        return tuple(work)

    def destroy_selected(c):
        if c.choice is None or (c.choice.choice.source_id, c.choice.choice.player_id) != (c.source_id, c.player_id):
            raise ResolutionError('Fetid lost its original complete enemy selection')
        refs = tuple(MinionReference(**json.loads(o.id)) for o in c.choice.selected)
        for ref, item in zip(refs, c.choice.selected):
            if (ref.entity_id, ref.card_id, ref.player_id) != (item.entity_id, item.card_id, 3-c.player_id):
                raise ResolutionError('Fetid rebound an original enemy arrow')
        ids = tuple(ref.entity_id for ref in refs if live_minion(c.state, ref) is not None)
        return (DestroyBatch(ids, c.source_id),) if ids else ()

    registry.register_trigger_condition(PREFIX+'rune_play', lambda c: destination(c) is not None)
    for name, fn in (('shift', shift), ('body', body), ('destroy_selected', destroy_selected)):
        registry.register_behavior(PREFIX+name, fn)
    data = load_batch()
    for entry in data['cards']+data['dependencies']:
        raw = entry['record']; cid = raw['id']; meta = metadata_from_record(raw); runes = meta.runes
        expected = (0, 0, 0) if cid == CARD else COUNTS[cid]
        if ((raw['type'], raw['cost'], raw['attack'], raw['health']) != ('MINION', 7, 9, 6) or
                runes is None or (runes.blood, runes.frost, runes.unholy) != expected or
                bool(raw['tags'].get('BATTLECRY')) != (cid != CARD) or set(meta.tribes) != {'beast', 'undead'}):
            raise TargetValidationError('Fetid lost its original body, full Rune identity or real Battlecry')
        definition = CardDefinition(cid, raw['name'], CardType.MINION, cost=7, attack=9, health=6,
            metadata=meta, hand_progress=PROGRESS, battlecry=None if cid == CARD else PREFIX+'body')
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
