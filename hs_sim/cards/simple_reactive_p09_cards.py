"""P09 native health witnesses, completed Battlecry plays and own-turn facts."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.effects import Damage, InvokeBehavior, RefreshMana
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.imbue import Imbue
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, HealthFlow, Keyword, SpellSchool, TargetSpec, TriggerSpec, Zone
from hs_sim.engine.owner_turns import validate_history
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference, live_minion
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .played_minion_keyword_cards import original_recipient, played_minion

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-reactive-p09-v1.json'
BATCH_HASH = '3c75643ae4184d55d64664ae5263d1492ceedf2cf46c99320a755a63e41cae50'
EVENTUALITY = 'END_000'
RIOTER = 'JAIL_029'
GOON = 'JAIL_802'
WILDSPEAKER = 'MEND_041'
ROOTS = (EVENTUALITY, RIOTER, GOON, WILDSPEAKER)
PREFIX = 'cards.simple_reactive_p09.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('P09 lost its complete reviewed source pin')
    if (tuple(x['record']['id'] for x in data['cards']) != ROOTS or data['dependencies'] or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != ('END_000p',) or data['skipped']):
        raise TargetValidationError('Unreviewed P09 roots or dependencies')
    for key in ('cards', 'dependencies', 'existing_dependencies', 'evidence_only', 'skipped'):
        for row in data[key]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('P09 complete source row changed')
    links = [o['face'].get('childIds') for o in data['official_observations']['observations'] if o['card_id'] == EVENTUALITY]
    if links != [[121243], [121243]]:
        raise TargetValidationError('Eventuality lost its exact official Imbue power association')
    return data


def register_simple_reactive_p09_cards(registry):
    data = load_batch();dependency, = data['existing_dependencies']
    if canonical_digest(asdict(registry.card('END_000p'))) != dependency['definition_sha256']:
        raise TargetValidationError('P09 requires the unchanged complete existing Bronze power')

    def rioter(c):
        result = c.health_result
        if result is None:
            raise ResolutionError('Rioter requires its original settled health result')
        if (not living_source(c) or result.flow != HealthFlow.DAMAGE.value or result.damage_dealt <= 0 or
                result.target_kind != CardType.MINION.value or result.target_controller != c.player_id or
                result.health_after <= 0 or result.doomed_after):
            return ()
        original = MinionReference(result.target_id, result.target_controller, result.target_card_id,
                                   result.target_zone_epoch, result.target_entered_order)
        return (BuffCapturedMinion(original, 1, 0, c.source_id),) if live_minion(c.state, original) is not None else ()

    def goon(c):
        row = played_minion(c)
        if row is None:return ()
        if row.submitted_cost is None:
            raise ResolutionError('Goon lost its original submitted Battlecry ability inventory')
        if not any(a.kind == 'battlecry' and not a.consumed for a in row.submitted_cost.quote.quote_input.abilities):
            return ()
        return (InvokeBehavior(PREFIX+'goon_current', row.source_id, row.player_id, c.source_id, row.id),)

    def goon_current(c):
        target = original_recipient(c, c.play)
        return (BuffCapturedMinion(MinionReference.capture(target), 1, 1, c.target_id),) if target is not None else ()

    def wildspeaker(c):
        validate_history(c.state)
        previous = next((t for t in reversed(c.state.owner_turn_history) if t.player_id == c.player_id and t.closed), None)
        played = previous is not None and any(p.player_id == c.player_id and p.kind == CardType.MINION and
            p.played_face.owner_turn_id == previous.id for p in c.state.play_history)
        return () if played else (RefreshMana(c.player_id, 3),)

    bodies = {
        'eventuality': lambda c: (Damage(c.target_id, 2, c.source_id, DamageKind.SPELL), Imbue(c.player_id, c.source_id)),
        'rioter': rioter, 'goon': goon, 'goon_current': goon_current, 'wildspeaker': wildspeaker,
    }
    for name, body in bodies.items():registry.register_behavior(PREFIX+name, body)
    for row in data['cards']:
        raw = row['record'];cid = raw['id'];kind = CardType(raw['type'].lower());kwargs = {}
        if raw['collectible'] is not True:
            raise TargetValidationError('P09 requires complete collectible roots')
        if cid == EVENTUALITY:
            if raw['tags'].get('SPELL_SCHOOL') != 6:
                raise TargetValidationError('Eventuality requires its original Shadow spell face')
            kwargs.update(on_play=PREFIX+'eventuality',spell_school=SpellSchool.SHADOW,
                targeting=TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION)))
        else:
            kwargs.update(attack=raw['attack'],health=raw['health'])
            if cid == WILDSPEAKER:kwargs.update(keywords=(Keyword.TAUNT,),battlecry=PREFIX+'wildspeaker')
            else:kwargs['triggers'] = (TriggerSpec('health_resolved' if cid == RIOTER else 'card_played',
                                                   PREFIX+('rioter' if cid == RIOTER else 'goon')),)
        card = CardDefinition(cid,raw['name'],kind,cost=raw['cost'],
            metadata=replace(metadata_from_record(raw),deck_identity=cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
