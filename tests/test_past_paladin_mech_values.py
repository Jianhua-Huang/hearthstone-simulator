"""Native effects behind an explicit four-card adapter fixture, never a cropped live pool."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import past_paladin_mech_values as native
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p89_cards import QUERIES
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game, Keyword,
    PlayerSetup, PlayerSpellCountCostSpec, ResolutionError, Scenario, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Destroy,
    InvokeBehavior, RequestChoice, Silence)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import RepeatCostFilter, RepeatMatchSpec, SpellRepeatSpec
from hs_sim.engine.pools import (GenerationContext, PoolCard, PoolDefinition, PoolMember,
    matches_metadata, resolve_candidates, sample_candidates)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError, canonical_digest
from tools import card_batch as batch

P = 'k586.'
SOURCE, POOL = 'TIME_016','constructed.past.cards'
CONTEXT = GenerationContext(P+'explicit-four-native-adapter-fixture','experimental')
UNIT, UNTYPED, NEUTRAL, WATCH, KILL, QUIET, GIVE, FILL_KILL, HOLY, OTHER, DRIVER, FAILED, BAD, HISTORY, DOUBLE, NATIVE, OLD, COUNTER = (
    P+x for x in ('unit','untyped','neutral','watch','kill','silence','give','fill-kill','holy','other',
        'driver','failed','bad-auto','history','double','native-repeat','old-root-price','counter'))
META = CardMetadata(False,(CardClass.PALADIN,),None)
TYPE_IDS = tuple(P+'type.'+t for t in native.TYPES)
DUAL, ALL = P+'dual', P+'all'


@lru_cache(None)
def host(mode='normal', role='writer'):
    f = build_cn37_local_pool_format(); r = f.registry
    reference = batch.read(native.REFERENCE_PATH)
    ids = reference['candidate_ids'] if mode == 'full-reference' else native.LEAVES
    if mode == 'full-reference':
        for row in reference['candidate_records']:
            raw = row['record']; cid = raw['id']
            if cid in r.pool_cards: continue
            printed = PoolCard.from_definition(r.card(cid)) if cid in r.cards else PoolCard(cid,CardType.MINION,
                raw['cost'],metadata_from_record(raw),battlecry=bool(raw['tags'].get('BATTLECRY')),
                deathrattle=bool(raw['tags'].get('DEATHRATTLE')),choose_one=False,attack=raw['attack'])
            r.register_pool_card(printed)
    r.register_pool(PoolDefinition(POOL,P+mode,CONTEXT.target_id,CONTEXT.mode,
        tuple(PoolMember(cid) for cid in ids),complete=True))
    def fail(c): raise ResolutionError('K586 deliberate continuation failure')
    def watch(c):
        e = c.event
        if e.player_id != c.player_id: return ()
        wants_draw = mode == 'draw-wait' and e.kind == 'card_drawn' and len(c.state.draw_history) == 1
        wants_giant = (mode == 'giant-wait' and e.kind == 'card_added_to_hand' and
            c.state.entities[e.target_id].card_id == native.GIANT)
        wants_cast = (mode == 'cast-wait' and e.kind == 'spell_cast_started' and
            c.state.cast_history[-1].card_id == HOLY and c.state.cast_history[-1].origin == 'effect')
        if not (wants_draw or wants_giant or wants_cast): return ()
        return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('fault','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(P+'fail',fail); r.register_behavior(WATCH,watch)
    r.register_behavior(HOLY,lambda c:()); r.register_behavior(OTHER,lambda c:())
    r.register_behavior(FAILED,lambda c:())
    scripts = {KILL:lambda c:(Destroy(c.target_id,c.source_id),),QUIET:lambda c:(Silence(c.target_id),),
        GIVE:lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        FILL_KILL:lambda c:(AddToHand(c.player_id,KILL,c.source_id),Destroy(c.target_id,c.source_id)),
        DRIVER:lambda c:(CastSpell(c.player_id,HOLY,c.source_id),),
        BAD:lambda c:(CastSpell(c.player_id,FAILED,c.source_id),),
        HISTORY:lambda c:(RecastSpell(player_id=c.player_id,cast_id=next(v.id for v in c.state.cast_history
            if v.player_id==c.player_id and v.card_id==HOLY),source_id=c.source_id),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.MINION if cid in (DRIVER,BAD,HISTORY) else CardType.SPELL,
            health=2 if cid in (DRIVER,BAD,HISTORY) else 0,metadata=META,
            **({'battlecry':cid} if cid in (DRIVER,BAD,HISTORY) else {'on_play':cid,'requires_target':cid in (KILL,QUIET,GIVE,FILL_KILL)})))
    for cid,tribes in ((UNIT,('mech',)),(UNTYPED,()),(DUAL,('mech','dragon')),(ALL,('all',)),
            *zip(TYPE_IDS,((t,) for t in native.TYPES))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=1,health=2,
            metadata=replace(META,tribes=tribes)))
    r.register_card(CardDefinition(NEUTRAL,NEUTRAL,CardType.MINION,health=2,metadata=replace(META,classes=(CardClass.NEUTRAL,))))
    r.register_card(CardDefinition(HOLY,HOLY,CardType.SPELL,cost=1,on_play=HOLY,spell_school=SpellSchool.HOLY,metadata=META))
    r.register_card(CardDefinition(OTHER,OTHER,CardType.SPELL,on_play=OTHER,spell_school=SpellSchool.FEL,metadata=META))
    from hs_sim.engine.model import TargetSpec
    r.register_card(CardDefinition(FAILED,FAILED,CardType.SPELL,on_play=FAILED,spell_school=SpellSchool.HOLY,
        metadata=META,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.LOCATION,),relation='enemy')))
    r.register_card(CardDefinition(OLD,OLD,CardType.MINION,cost=10,health=2,metadata=META,
        player_spell_count_cost=PlayerSpellCountCostSpec()))
    for cid,spec in ((DOUBLE,SpellRepeatSpec(2,class_mode='any')),(NATIVE,SpellRepeatSpec(2,class_mode='any',
            match=RepeatMatchSpec(recipient_cost=RepeatCostFilter('cast_quote',minimum=1,maximum=1))))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=3,metadata=META,spell_repeats=(spec,)))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
        triggers=tuple(TriggerSpec(e,WATCH) for e in ('card_drawn','card_added_to_hand','spell_cast_started'))))
    r.register_behavior(COUNTER,lambda c:(CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id!=c.player_id and c.state.entities[c.event.source_id].card_id==HOLY else ())
    r.register_card(CardDefinition(COUNTER,COUNTER,CardType.MINION,health=3,metadata=META,
        triggers=(TriggerSpec('card_committed',COUNTER),)))
    r.validate(); return f


def seed_for(cid):
    f = host(); candidates = resolve_candidates(f.registry,CONTEXT,POOL,QUERIES[SOURCE],source_card_id=SOURCE)
    return next(seed for seed in range(1000) if cid in sample_candidates(Random(seed),candidates,3,replacement=False))


class PastPaladinMechValueTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory = staticmethod(lambda mode,role:host(mode,role).registry)
    mode = 'normal'

    def game(self, desired=native.TOTEM, *, hand=(),deck=(),own=(),enemy=(),player=1,mode='normal',enemy_hand=()):
        self.mode = mode; f = host(mode)
        if mode.endswith('-wait'): own = (WATCH,*own)
        players = tuple(PlayerSetup('HERO_04',hand=(SOURCE,*hand) if p==player else enemy_hand,
            deck=deck if p==player else (),board=own if p==player else enemy,
            mana=60,max_mana=60,mana_cap=60) for p in (1,2))
        return Game.from_scenario(Scenario(players,active_player=player,seed=seed_for(desired),
            generation_context=CONTEXT),f.registry)

    def acquire(self,g,cid,player=1):
        self.play(g,SOURCE,player=player); q=g.state.pending_choice
        self.assertEqual(len(q.options),3)
        self.choose(g,next(o.id for o in q.options if o.card_id==cid))
        e=self.entity(g,cid,player); card=g.registry.card(cid)
        self.assertEqual((e.attack,e.max_health),(card.attack+5,card.health+5)); return e

    def price(self,g,cid=native.LIGHTBOT,player=1):
        return quote_unselected_cost(g.state,g.registry,self.entity(g,cid,player)).amount

    def test_complete_reference_has_all_27_raw_candidates_and_56_primary_faces_independent_of_coverage(self):
        data=native.load_batch(); ref=batch.read(native.REFERENCE_PATH); raw={v['id']:v for v in batch.read(ref['source'])}
        sets=set(ref['past_set_policy']['set_ids']); query=QUERIES[SOURCE]; ids=[]
        from hs_sim.engine.model import CardClass
        for v in raw.values():
            if not v['collectible'] or v['type']!='MINION' or v['card_set_id'] not in sets:continue
            if matches_metadata(query,card_id=v['id'],kind=CardType.MINION,cost=v['cost'],meta=metadata_from_record(v),
                    spell_school=None,keywords=(),current_class=CardClass.PALADIN): ids.append(v['id'])
        self.assertEqual(sorted(ids),ref['candidate_ids']); self.assertEqual(len(ids),27)
        for row in ref['candidate_records']: self.assertEqual(row['record'],raw[row['record']['id']])
        for face in ref['official_observations']:
            cid=face['card_id']; batch.check_face(raw[cid],face['face'],face['locale'],
                ref['display_normalizations'].get(cid),numeric_normalizations=ref['numeric_normalizations'].get(cid))
        self.assertEqual(len(ref['official_observations']),56); self.assertEqual(len(data['official_observations']),10)
        for face in data['official_observations']:
            cid=face['card_id']; batch.check_face(raw[cid],face['face'],face['locale'],
                data['display_normalizations'].get(cid),numeric_normalizations=data['numeric_normalizations'].get(cid))
        self.assertFalse(ref['membership_uses_executable_coverage']); self.assertFalse(ref['runtime_bindings_added'])
        self.assertFalse(data['cn_calibrated']); self.assertFalse(data['formal_pool_complete'])

    def test_real_discovery_adapter_grants_each_native_plus_five_then_pays_its_actual_cost(self):
        for cid in native.LEAVES:
            with self.subTest(cid=cid):
                g=self.game(cid); self.acquire(g,cid)
                expected=g.registry.card(cid).cost-(1 if cid==native.LIGHTBOT else 0)
                self.assertEqual(self.price(g,cid),expected); self.play(g,cid)
                self.assertEqual(g.state.play_history[-1].cost,expected)
                self.assertEqual(g.state.players[1].mana,57-expected)
        self.portable(g)

    def test_jukebox_summons_real_recruit_only_on_owners_end_for_both_seats(self):
        for p in (1,2):
            g=self.game(player=p); self.acquire(g,native.TOTEM,p); self.play(g,native.TOTEM,player=p)
            g.apply(EndTurn(p)); recruit=self.entity(g,native.RECRUIT,p,'board')
            self.assertEqual((recruit.attack,recruit.max_health),(1,1))
            g.apply(EndTurn(3-p)); self.assertEqual(sum(g.state.entities[i].card_id==native.RECRUIT for i in g.state.players[p].board),1)
            g.apply(EndTurn(p)); self.assertEqual(sum(g.state.entities[i].card_id==native.RECRUIT for i in g.state.players[p].board),2)

    def test_jukebox_silence_full_board_and_control_use_original_lifecycles(self):
        g=self.game(hand=(QUIET,)); self.acquire(g,native.TOTEM); root=self.play(g,native.TOTEM)
        self.play(g,QUIET,root); g.apply(EndTurn(1)); self.assertFalse(any(g.state.entities[i].card_id==native.RECRUIT for i in g.state.players[1].board))
        g=self.game(own=(UNIT,)*6); self.acquire(g,native.TOTEM); self.play(g,native.TOTEM)
        g.apply(EndTurn(1)); self.assertEqual(len(g.state.players[1].board),7)
        g=self.game(hand=(GIVE,)); self.acquire(g,native.TOTEM); root=self.play(g,native.TOTEM)
        self.play(g,GIVE,root); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(self.entity(g,native.RECRUIT,2,'board').controller,2)

    def test_lightbot_counts_manual_repeated_automatic_and_history_holy_casts_not_other_schools(self):
        g=self.game(native.LIGHTBOT,hand=(HOLY,OTHER,DRIVER,HISTORY,DOUBLE))
        self.acquire(g,native.LIGHTBOT); self.assertEqual(self.price(g),4)
        self.play(g,DOUBLE); self.play(g,HOLY); self.assertEqual(self.price(g),2)
        self.play(g,OTHER); self.assertEqual(self.price(g),2)
        self.play(g,DRIVER); self.assertEqual(self.price(g),1)
        self.play(g,HISTORY); self.assertEqual(self.price(g),0)
        self.assertEqual([v.origin for v in g.state.cast_history if v.card_id==HOLY],['hand','repeat','effect','history'])
        self.portable(g)

    def test_native_automatic_repetition_is_real_cast_material_but_old_root_price_keeps_old_operand(self):
        g=self.game(native.LIGHTBOT,hand=(DRIVER,OLD),own=(NATIVE,)); self.acquire(g,native.LIGHTBOT)
        self.play(g,DRIVER); self.assertEqual(self.price(g),2)
        rows=[v for v in g.state.cast_history if v.card_id==HOLY]
        self.assertEqual([(v.origin,v.iteration) for v in rows],[('effect',1),('native_repeat',2)])
        self.assertEqual(self.price(g,OLD),9)  # Only the real TIME_016 hand root counts for the older profile.
        self.play(g,native.LIGHTBOT); self.assertEqual(g.state.play_history[-1].cost,2); self.portable(g)

    def test_lightbot_gigantic_is_printed_eight_and_uses_same_global_count_without_source_stat_inheritance(self):
        g=self.game(native.LIGHTBOT,hand=(HOLY,HOLY)); self.play(g,HOLY)
        self.acquire(g,native.LIGHTBOT); self.assertEqual(self.price(g),3)
        self.play(g,native.LIGHTBOT); giant=self.entity(g,native.GIANT)
        self.assertEqual((giant.attack,giant.max_health),(8,8)); self.assertEqual(self.price(g,native.GIANT),6)
        self.play(g,HOLY); self.assertEqual(self.price(g,native.GIANT),5)
        self.play(g,native.GIANT); self.assertEqual(g.state.play_history[-1].cost,5)
        self.assertFalse(any(g.state.entities[i].card_id==native.GIANT for i in g.state.players[1].hand)); self.portable(g)

    def test_pending_automatic_holy_payload_does_not_reduce_cost_until_accepted_and_wait_is_portable(self):
        g=self.game(native.LIGHTBOT,hand=(DRIVER,),mode='cast-wait'); self.acquire(g,native.LIGHTBOT)
        self.play(g,DRIVER); self.assertEqual(self.price(g),4); before=g.snapshot(); restored=self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)
        for current in (g,restored): self.choose(current); self.assertEqual(self.price(current),3)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_failed_countered_and_opponent_holy_attempts_do_not_reduce_our_price(self):
        g=self.game(native.LIGHTBOT,hand=(HOLY,BAD),enemy=(COUNTER,),enemy_hand=(HOLY,))
        self.acquire(g,native.LIGHTBOT); self.play(g,HOLY); self.play(g,BAD); self.assertEqual(self.price(g),4)
        self.assertEqual([v.failure for v in g.state.cast_history if v.card_id in (HOLY,FAILED)],['countered','no_target'])
        g.apply(EndTurn(1)); self.play(g,HOLY,player=2); self.assertEqual(self.price(g),4)

    def test_purator_draws_all_twelve_physical_types_skips_untyped_and_burns_only_real_overflow(self):
        g=self.game(native.PURATOR,deck=(*TYPE_IDS,UNTYPED)); self.acquire(g,native.PURATOR); self.play(g,native.PURATOR)
        self.assertEqual([v.card_id for v in g.state.draw_history],list(TYPE_IDS))
        self.assertEqual([v.outcome for v in g.state.draw_history],['hand']*10+['burned']*2)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[UNTYPED])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)

    def test_purator_checks_current_deck_neutral_condition_and_empty_deck_does_not_fatigue(self):
        for deck in ((NEUTRAL,*TYPE_IDS),()):
            g=self.game(native.PURATOR,deck=deck); self.acquire(g,native.PURATOR); rng=g._rng.getstate()
            self.play(g,native.PURATOR); self.assertEqual(g.state.draw_history,[]); self.assertEqual(g._rng.getstate(),rng)
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)

    def test_purator_multi_and_all_types_consume_each_physical_card_once(self):
        g=self.game(native.PURATOR,deck=(ALL,ALL,DUAL,DUAL,UNTYPED)); self.acquire(g,native.PURATOR); self.play(g,native.PURATOR)
        self.assertEqual(len(g.state.draw_history),4)
        self.assertEqual(len({v.entity_id for v in g.state.draw_history}),4)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[UNTYPED])

    def test_securitybot_draws_original_other_minion_sets_stats_and_cost_to_five_then_real_play(self):
        g=self.game(native.SECURITY,hand=(KILL,UNIT),deck=(native.SECURITY,UNIT))
        held=self.entity(g,UNIT).id; self.acquire(g,native.SECURITY); root=self.play(g,native.SECURITY); self.play(g,KILL,root)
        draw=g.state.draw_history[-1]; target=g.state.entities[draw.entity_id]
        self.assertNotEqual(target.id,held); self.assertEqual((target.attack,target.max_health),(5,5)); self.assertEqual(quote_unselected_cost(g.state,g.registry,target).amount,5)
        self.assertEqual((g.state.entities[held].attack,g.state.entities[held].max_health),(1,2))
        from hs_sim.engine import PlayCard
        g.apply(PlayCard(1,target.id)); self.assertEqual(g.state.play_history[-1].cost,5); self.portable(g)

    def test_securitybot_excludes_same_identity_and_burned_draw_has_no_fake_hand_reward(self):
        g=self.game(native.SECURITY,hand=(KILL,),deck=(native.SECURITY,)); self.acquire(g,native.SECURITY)
        root=self.play(g,native.SECURITY); rng=g._rng.getstate(); self.play(g,KILL,root)
        self.assertEqual(g.state.draw_history,[]); self.assertEqual(g._rng.getstate(),rng)
        g=self.game(hand=(FILL_KILL,)*9,own=(native.SECURITY,),deck=(UNIT,))
        root=self.entity(g,native.SECURITY,zone='board').id; self.play(g,FILL_KILL,root)
        draw=g.state.draw_history[-1]; self.assertEqual(draw.outcome,'burned')
        target=g.state.entities[draw.entity_id]; self.assertEqual((target.attack,target.max_health),(1,2))

    def test_original_draw_group_waits_restore_clone_replay_and_failure_is_atomic(self):
        for cid in (native.PURATOR,native.SECURITY):
            with self.subTest(cid=cid):
                g=self.game(cid,hand=(KILL,),deck=(UNIT,TYPE_IDS[1]),mode='draw-wait'); self.acquire(g,cid)
                root=self.play(g,cid)
                if cid==native.SECURITY:self.play(g,KILL,root)
                before=g.snapshot(); restored=self.portable(g)
                with self.assertRaises(ResolutionError):self.choose(g,'fault')
                self.assertEqual(g.snapshot(),before)
                for current in (g,restored): self.choose(current)
                self.assertEqual(g.snapshot(),restored.snapshot()); self.portable(g)

    def test_gigantic_creation_wait_preserves_actual_discount_and_does_not_duplicate_derivative(self):
        g=self.game(native.LIGHTBOT,hand=(HOLY,),mode='giant-wait'); self.play(g,HOLY); self.acquire(g,native.LIGHTBOT)
        self.play(g,native.LIGHTBOT); self.assertEqual(self.price(g,native.GIANT),6); restored=self.portable(g)
        for current in (g,restored): self.choose(current)
        self.assertEqual(g.snapshot(),restored.snapshot()); self.assertEqual(sum(g.state.entities[i].card_id==native.GIANT for i in g.state.players[1].hand),1)

    def test_full_27_reference_cannot_execute_missing_members_or_borrow_old_bound_inventory(self):
        g=self.game(mode='full-reference'); before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'SC_412'): self.play(g,SOURCE)
        self.assertEqual(g.snapshot(),before)
        f=host()
        with self.assertRaisesRegex(UnsupportedDefinitionError,'Unreviewed generation scope'):
            resolve_candidates(f.registry,f.context,POOL,QUERIES[SOURCE],source_card_id=SOURCE,exclude_source_by_rule=True)
        ref=batch.read(native.REFERENCE_PATH)
        self.assertEqual([cid for cid in ref['candidate_ids'] if cid not in f.registry.cards],['SC_412','TSC_083'])

    def test_changed_final_existing_dependency_leaves_registry_without_half_registered_cards(self):
        r=build_registry()
        for cid in native.DEPENDENCIES:r._cards.pop(cid); r._pool_cards.pop(cid)
        r._cards[native.RECRUIT]=replace(r.card(native.RECRUIT),health=2)
        before=(dict(r.cards),dict(r.pool_cards),dict(r._behaviors))
        with self.assertRaises(TargetValidationError):native.register_past_paladin_mech_values(r)
        self.assertEqual((dict(r.cards),dict(r.pool_cards),dict(r._behaviors)),before)

    def test_own_cost_is_visible_but_other_hand_and_intrinsic_prefix_are_private(self):
        g=self.game(native.LIGHTBOT,hand=(HOLY,),player=2); self.play(g,HOLY,player=2); self.acquire(g,native.LIGHTBOT,2)
        self.assertEqual(self.price(g,player=2),3)
        self.assertIn(native.LIGHTBOT,json.dumps(g.observe(2))); self.assertNotIn(native.LIGHTBOT,json.dumps(g.observe(1)))
        for player in (1,2):
            view=json.dumps(g.observe(player))
            for field in ('player_spells','cast_rows','reference_canonical_sha256','rng_state','resolution_frame'):
                self.assertNotIn('"'+field+'"',view)


if __name__=='__main__':unittest.main()
