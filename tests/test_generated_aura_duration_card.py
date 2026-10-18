"""Gelbin Triumph: current-format Aura selection and original duration material."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.generated_aura_duration_card import CARD, load_batch
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (AbilityInstance, CardClass, CardDefinition, CardMetadata,
    CardType, EndTurn, Game, PlayCard, PlayerSetup, ResolutionError, Scenario,
    SelectChoice, SnapshotError, SpellRepeatSpec, TriggerSpec, Zone)
from hs_sim.engine.aura_duration import BIND_EVENT, EVENT, KIND, GenerateAuraWithExtraTurn, maximum_duration
from hs_sim.engine.effects import ChoiceOption, GainArmor, InvokeBehavior, RequestChoice
from hs_sim.engine.model import EndTurnSpec
from hs_sim.engine.hand_upgrades import UpgradeHandCard
from hs_sim.engine.pool_summons import query_from_dict
from hs_sim.engine.pools import (GenerateFromPool, GenerationContext, PoolCard,
    PoolDefinition, PoolMember, PoolQuery, matches_metadata)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell, CastStoredSpell
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard

P = 'k219.'
NOP, PLAIN, REPEAT = (P+x for x in ('nop','plain','repeat'))
META = CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
AURAS = ('CATA_480','END_011','JAIL_327','TIME_700','TTN_851')
UNKNOWN = 'BE_146'


@lru_cache(None)
def registry(role):
    from hs_sim.cards import build_registry
    r=build_registry(); data=load_batch()
    r.register_behavior(NOP,lambda c: ())
    r.register_card(CardDefinition(NOP,NOP,CardType.SPELL,on_play=NOP,metadata=META))
    r.register_pool_card(PoolCard.from_definition(r.card(NOP)))
    r.register_card(CardDefinition(PLAIN,PLAIN,CardType.MINION,attack=1,health=10,metadata=META))
    r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=20,metadata=META,
        spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
    r.register_behavior(P+'end_body',lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition(P+'end_body',P+'end_body',CardType.MINION,health=20,metadata=META,
        triggers=(TriggerSpec('turn_ended',P+'end_body',EndTurnSpec()),)))
    row=next(x for x in data['evidence_only'] if x['record']['id']==UNKNOWN)['record']
    if UNKNOWN not in r.pool_cards:
        r.register_pool_card(PoolCard.from_definition(CardDefinition(UNKNOWN,row['name'],CardType.SPELL,
            cost=row['cost'],metadata=metadata_from_record(row))))
    modes={'all':AURAS+(NOP,), 'empty':(NOP,), 'unknown':('TTN_851',UNKNOWN),
           **{cid:(cid,) for cid in AURAS}}
    for mode,ids in modes.items():
        r.register_pool(PoolDefinition('constructed.cards','k219-v1',P+mode,'experimental',
            tuple(PoolMember(cid) for cid in ids),complete=True))
    def original(c):
        return next(c.state.entities[i] for i in c.state.players[c.player_id].hand
                    if any(a.kind==KIND for a in c.state.entities[i].abilities))
    for name in ('copy_current','copy_base','move','transfer','morph','fresh_cast','stored_cast'):
        key=P+name
        def body(c,name=name):
            if name=='fresh_cast': return (CastSpell(c.player_id,'TTN_851',c.source_id),)
            ref=CardReference.capture(original(c))
            if name=='stored_cast':return (CastStoredSpell(ref,c.player_id,c.source_id),)
            if name.startswith('copy_'):
                return (CopyCard(ref,c.player_id,mode=name[5:],source_id=c.source_id),)
            if name=='morph': return (UpgradeHandCard(ref,NOP,c.source_id),)
            return (MoveCard(ref,3-c.player_id if name=='transfer' else c.player_id,
                Zone.HAND if name=='transfer' else Zone.DECK,
                position='bottom' if name=='transfer' else 'top',source_id=c.source_id),)
        r.register_behavior(key,body)
        r.register_card(CardDefinition(key,key,CardType.SPELL,on_play=key,metadata=META))
    def fail(c): raise ResolutionError('Deliberate Aura rollback')
    r.register_behavior(P+'raise',fail)
    def nested(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!='TTN_851':return ()
        available=[c.state.entities[i] for i in c.state.players[c.player_id].hand
                   if any(a.kind==KIND for a in c.state.entities[i].abilities)]
        return () if not available else (CastStoredSpell(CardReference.capture(available[0]),c.player_id,c.source_id),)
    r.register_behavior(P+'nested',nested)
    r.register_card(CardDefinition(P+'nested',P+'nested',CardType.MINION,health=20,metadata=META,
        triggers=(TriggerSpec('spell_cast_started',P+'nested'),)))
    def wait(c):
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('fail','Fail',(InvokeBehavior(P+'raise',c.source_id,c.player_id),))),c.source_id),)
    for name,event in (('created_wait','card_created'),('installed_wait','player_effect_added')):
        key=P+name
        def watcher(c,name=name):
            source=c.state.entities.get(c.event.source_id)
            if source is None: return ()
            if name=='created_wait':
                if source.card_id!=CARD: return ()
                target=c.state.entities[c.event.target_id]
                if not any(a.kind==KIND for a in target.abilities):
                    raise ResolutionError('Creation notification preceded its duration attachment')
            elif source.card_id not in AURAS: return ()
            return wait(c)
        r.register_behavior(key,watcher)
        r.register_card(CardDefinition(key,key,CardType.MINION,health=20,metadata=META,
            triggers=(TriggerSpec(event,key),)))
    query=PoolQuery(kinds=(CardType.SPELL,),collectible=True,card_ids=tuple(data['aura_ids']))
    r.register_behavior(P+'wait_generate',lambda c: (*wait(c),GenerateAuraWithExtraTurn(
        GenerateFromPool(c.player_id,'constructed.cards',query,source_id=c.source_id))))
    r.register_card(CardDefinition(P+'wait_generate',P+'wait_generate',CardType.SPELL,
        on_play=P+'wait_generate',metadata=META))
    r.validate();return r


class GeneratedAuraDurationTests(unittest.TestCase):
    def game(self,mode='TTN_851',owner=1,hand=(CARD,),board=()):
        players=[PlayerSetup('HERO_04',deck=(PLAIN,)*12,mana=30,max_mana=30,mana_cap=30) for _ in (1,2)]
        players[owner-1]=replace(players[owner-1],hand=hand,board=board)
        return Game.from_scenario(Scenario(tuple(players),active_player=owner,seed=219,
            generation_context=GenerationContext(P+mode,'experimental')),registry('writer'))

    def play_id(self,g,eid):
        p=g.state.active_player
        position=len(g.state.players[p].board) if g.state.entities[eid].kind==CardType.MINION else None
        g.apply(PlayCard(p,eid,position=position))

    def play(self,g,cid):
        eid=next(i for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id==cid)
        self.play_id(g,eid);return eid

    def boost(self,g,owner=None):
        owner=owner or g.state.active_player
        return next(g.state.entities[i] for i in g.state.players[owner].hand
                    if any(a.kind==KIND for a in g.state.entities[i].abilities))

    def install(self,g):
        self.play(g,CARD);eid=self.boost(g).id;self.play_id(g,eid);return eid

    def check(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        other=registry('reader' if g.registry is registry('writer') else 'writer')
        self.assertIsNot(other,g.registry)
        restored=Game.from_snapshot(saved,other)
        self.assertEqual(restored.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),other).snapshot(),saved)
        return restored

    def choose(self,g,option='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option,)))

    def end(self,g):g.apply(EndTurn(g.state.active_player))

    def rehash(self,saved):
        saved['events_hash']=canonical_hash(saved['events'])
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        return saved

    def test_complete_tag_index_and_bilingual_source(self):
        data=load_batch();self.assertEqual(len(data['aura_ids']),16)
        self.assertEqual(len(data['official_observations']),2)
        self.assertEqual((registry('writer').card(CARD).cost,len(data['cards'])),(1,1))
        for cid in AURAS:
            d=registry('writer').card(cid)
            self.assertEqual(registry('writer').player_effect(d.ongoing_effect_id).kind,'aura')

    def test_all_five_candidate_auras_keep_native_clocks_and_gain_one_unit(self):
        for cid in AURAS:
            g=self.game(mode=cid);eid=self.install(g)
            spec=g.registry.player_effect(g.registry.card(cid).ongoing_effect_id)
            effect=g.state.players[1].player_effects[-1]
            self.assertEqual(effect.remaining_turns,spec.duration+1)
            cast=g.state.cast_history[effect.aura_duration_cast_id-1]
            self.assertEqual((cast.source_id,len(cast.aura_duration_grants)),(eid,1))
            self.assertEqual(g.state.players[1].mana,29-g.registry.card(cid).cost)
        self.check(g)

    def test_actual_format_pool_excludes_unlisted_auras_and_other_spells(self):
        g=self.game(mode='all');self.play(g,CARD);card=self.boost(g)
        self.assertIn(card.card_id,AURAS)
        self.assertEqual(len([a for a in card.abilities if a.kind==KIND]),1)
        self.check(g)

    def test_second_seat_receives_its_own_independent_extended_aura(self):
        g=self.game(owner=2);eid=self.install(g)
        effect=g.state.players[2].player_effects[-1]
        self.assertEqual((effect.remaining_turns,effect.source_id),(3,eid))
        self.assertEqual(g.state.players[1].player_effects,[]);self.check(g)

    def test_three_real_auras_previously_called_objectives_satisfy_timeways(self):
        for cid in ('CATA_480','END_011','TIME_700'):
            g=self.game(hand=(cid,'TIME_019'));self.play(g,cid);self.play(g,'TIME_019')
            self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27)

    def test_opponent_turn_clock_does_not_consume_own_ends(self):
        g=self.game();self.install(g)
        for left in (2,1,0):
            self.end(g);self.assertEqual(g.state.players[1].player_effects[0].remaining_turns,left+1)
            self.end(g)
            self.assertEqual([e.remaining_turns for e in g.state.players[1].player_effects],[] if left==0 else [left])
        self.check(g)

    def test_owner_end_aura_gets_four_real_summon_ticks(self):
        g=self.game(mode='JAIL_327');self.install(g)
        for n in range(4):
            self.end(g);self.assertEqual(len(g.state.players[1].board),n+1)
            self.assertEqual([e.remaining_turns for e in g.state.players[1].player_effects],[] if n==3 else [3-n])
            if n!=3:self.end(g)
        self.check(g)

    def test_owner_start_aura_gets_four_real_countdown_ticks(self):
        g=self.game(mode='END_011');self.install(g)
        for left in (3,2,1,0):
            self.end(g);self.end(g)
            self.assertEqual([e.remaining_turns for e in g.state.players[1].player_effects],[] if left==0 else [left])
        self.check(g)

    def test_extended_sandfury_keeps_double_end_body_through_fourth_tick(self):
        g=self.game(mode='CATA_480',board=(P+'end_body',));self.install(g)
        effect=g.state.players[1].player_effects[-1]
        self.assertEqual(maximum_duration(g.registry,effect),4)
        self.assertEqual(maximum_duration(g.registry,effect,g.state,1),4)
        for n in range(4):
            self.end(g);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2*(n+1))
            self.end(g)
        self.assertEqual(g.state.players[1].player_effects,[])
        self.end(g);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,9);self.check(g)

    def test_existing_same_named_plain_aura_keeps_its_original_duration(self):
        g=self.game(hand=(CARD,'TTN_851'));plain=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id=='TTN_851')
        self.play(g,CARD);boost=self.boost(g).id;self.play_id(g,plain);self.play_id(g,boost)
        self.assertEqual([(e.source_id,e.remaining_turns) for e in g.state.players[1].player_effects],[(plain,2),(boost,3)])
        self.check(g)

    def test_current_copy_inherits_independent_attachment_base_copy_does_not(self):
        for mode in ('current','base'):
            key=P+'copy_'+mode;g=self.game(hand=(CARD,key));self.play(g,CARD);original=self.boost(g)
            oldids={a.id for a in original.abilities};self.play(g,key)
            copies=[g.state.entities[i] for i in g.state.players[1].hand if i!=original.id and g.state.entities[i].card_id=='TTN_851']
            self.assertEqual(len(copies),1);copy=copies[0]
            grants=[a for a in copy.abilities if a.kind==KIND]
            self.assertEqual(len(grants),int(mode=='current'))
            self.assertTrue(not oldids.intersection(a.id for a in grants))
            self.play_id(g,copy.id)
            self.assertEqual(g.state.players[1].player_effects[-1].remaining_turns,3 if mode=='current' else 2)
            self.check(g)

    def test_physical_deck_move_and_draw_retain_attachment(self):
        g=self.game(hand=(CARD,P+'move'));self.play(g,CARD);eid=self.boost(g).id
        self.play(g,P+'move');self.assertEqual(g.state.entities[eid].zone,Zone.DECK)
        self.end(g);self.end(g)
        self.assertIn(eid,g.state.players[1].hand);self.play_id(g,eid)
        self.assertEqual(g.state.players[1].player_effects[-1].remaining_turns,3);self.check(g)

    def test_transferred_spell_gives_extended_aura_to_actual_caster(self):
        g=self.game(hand=(CARD,P+'transfer'));self.play(g,CARD);eid=self.boost(g).id
        self.play(g,P+'transfer');self.end(g);self.play_id(g,eid)
        self.assertEqual(g.state.players[1].player_effects,[])
        self.assertEqual(g.state.players[2].player_effects[-1].remaining_turns,3);self.check(g)

    def test_face_change_clears_native_aura_duration_attachment(self):
        g=self.game(hand=(CARD,P+'morph'));self.play(g,CARD);eid=self.boost(g).id;self.play(g,P+'morph')
        self.assertEqual(g.state.entities[eid].card_id,NOP)
        self.assertFalse(any(a.kind==KIND for a in g.state.entities[eid].abilities));self.check(g)

    def test_hand_repetitions_keep_original_material_and_independent_instances(self):
        g=self.game(board=(REPEAT,));self.install(g)
        effects=g.state.players[1].player_effects
        self.assertEqual([e.remaining_turns for e in effects],[3,3])
        casts=[c for c in g.state.cast_history if c.card_id=='TTN_851']
        self.assertEqual([c.origin for c in casts],['hand','repeat'])
        self.assertEqual(casts[0].aura_duration_grants,casts[1].aura_duration_grants)
        self.assertEqual(g.state.players[1].mana,27);self.check(g)

    def test_fresh_automatic_cast_does_not_borrow_old_physical_material(self):
        g=self.game(hand=(CARD,P+'fresh_cast'));self.install(g);self.play(g,P+'fresh_cast')
        self.assertEqual([e.remaining_turns for e in g.state.players[1].player_effects],[3,2]);self.check(g)

    def test_actual_stored_automatic_cast_retains_duration_without_hand_payment(self):
        g=self.game(hand=(CARD,P+'stored_cast'));self.play(g,CARD);eid=self.boost(g).id
        self.play(g,P+'stored_cast')
        effect=g.state.players[1].player_effects[-1]
        self.assertEqual((effect.source_id,effect.remaining_turns),(eid,3))
        self.assertEqual(g.state.players[1].mana,29);self.check(g)

    def test_nested_automatic_acceptance_uses_actual_cast_ids_not_start_order(self):
        g=self.game(hand=(CARD,CARD,P+'stored_cast'),board=(P+'nested',))
        self.play(g,CARD);self.play(g,CARD);self.play(g,P+'stored_cast')
        self.assertEqual([e.remaining_turns for e in g.state.players[1].player_effects],[3,3])
        ids=[dict(e.data)['cast_id'] for e in g.events if e.kind==EVENT]
        self.assertEqual(len(ids),2);self.assertGreater(ids[0],ids[1]);self.check(g)

    def test_created_notification_sees_grant_and_waiting_restores(self):
        g=self.game(board=(P+'created_wait',));self.play(g,CARD)
        self.assertIsNotNone(g.state.pending_choice);restored=self.check(g)
        for branch in (g,restored):self.choose(branch)
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_pending_typed_generation_request_and_whitelist_restore(self):
        g=self.game(hand=(P+'wait_generate',));self.play(g,P+'wait_generate')
        restored=self.check(g)
        for branch in (g,restored):self.choose(branch)
        self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(len([a for a in self.boost(g).abilities if a.kind==KIND]),1);self.check(g)

    def test_install_waiting_restores_original_cast_and_failure_rolls_back(self):
        g=self.game(board=(P+'installed_wait',));self.install(g);before=g.snapshot();restored=self.check(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before)
        for branch in (g,restored):self.choose(branch)
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_empty_complete_pool_is_rng_neutral_and_unknown_eligible_fails_atomically(self):
        g=self.game(mode='empty');before=g.snapshot()['rng_state'];self.play(g,CARD)
        self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertEqual(g.state.players[1].hand,[]);self.check(g)
        g=self.game(mode='unknown');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CARD)
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_private_receipts_and_corrupted_original_duration_are_rejected(self):
        g=self.game();self.install(g)
        for owner in (1,2):
            dto=json.dumps(g.observe(owner));self.assertNotIn(EVENT,dto);self.assertNotIn(BIND_EVENT,dto);self.assertNotIn('aura_duration_cast_id',dto)
        for mode in ('overflow','wrong_cast','lost_material','lost_installation'):
            saved=deepcopy(g.snapshot());effect=saved['state']['players']['1']['player_effects'][0]
            if mode=='overflow':effect['remaining_turns']=4
            elif mode=='wrong_cast':effect['aura_duration_cast_id']=1
            elif mode=='lost_material':
                saved['state']['cast_history'][-1]['aura_duration_grants']=[]
                effect['aura_duration_cast_id']=None;effect['remaining_turns']=2
            else:
                event=next(e for e in saved['events'] if e['kind']==BIND_EVENT)
                event['kind']='unused_private_test'
            with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry('reader'))

    def test_lost_original_cast_binding_after_first_tick_is_rejected(self):
        g=self.game();self.install(g);self.end(g);self.end(g)
        self.assertEqual(g.state.players[1].player_effects[0].remaining_turns,2)
        saved=deepcopy(g.snapshot());saved['state']['players']['1']['player_effects'][0]['aura_duration_cast_id']=None
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry('reader'))

    def test_query_identity_filter_and_pure_attachment_are_strict(self):
        for ids in (['TTN_851'],('TTN_851','TTN_851')):
            with self.assertRaises(ValueError):PoolQuery(card_ids=ids)
        q=PoolQuery(card_ids=('TTN_851',))
        self.assertEqual(query_from_dict(json.loads(json.dumps(asdict(q)))),q)
        self.assertFalse(matches_metadata(q,card_id=NOP,kind=CardType.SPELL,cost=0,meta=None,spell_school=None,keywords=()))
        with self.assertRaises(ValueError):AbilityInstance(1,KIND,source_id=1,attack=1)
        request=GenerateFromPool(1,'fixture',PoolQuery(kinds=(CardType.SPELL,),collectible=True,card_ids=('TTN_851',)),source_id=1)
        GenerateAuraWithExtraTurn(request)
        with self.assertRaises(ValueError):GenerateAuraWithExtraTurn(replace(request,count=2))


if __name__ == '__main__':unittest.main()
