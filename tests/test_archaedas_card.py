"""Actual Archaedas discovery, native Hammer material and original attack CAST."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.archaedas_card import CARD,WEAPON,load_batch,register_archaedas_card
from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,
    Registry,Scenario,SelectChoice,SnapshotError,TriggerSpec)
from hs_sim.engine.carved_spells import weapon_material
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (ChoiceOption,Damage,Destroy,Draw,InvokeBehavior,ModifyWeapon,
    RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass,CardMetadata,CostSpec,DamageKind,Rarity,TargetSpec,Zone
from hs_sim.engine.pools import (DiscoverFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,CopyCard,ModifyStoredCost,MoveCard
from tools.card_batch import check_face

P='fixture.archaedas.'
HERO,UNIT,ZERO,BOLT,FIVE,FOREIGN,HIDDEN,GHOST,COPY,BASE,RESET,DECK,DISCOUNT,ALTER,KILL,WATCH=(P+x for x in
    ('hero','unit','zero','bolt','five','foreign','hidden','ghost','copy','base','reset','deck','discount','alter','kill','watch'))
META=CardMetadata(True,(CardClass.SHAMAN,),Rarity.COMMON,tribes=())


@lru_cache(maxsize=None)
def registry(mode='normal',role='writer'):
    assert role in ('writer','reader')
    r=Registry('archaedas-'+mode);register_archaedas_card(r)
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,
        metadata=CardMetadata(False,(CardClass.SHAMAN,),Rarity.NONE,tribes=())))
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,attack=1,health=3,metadata=META))
    r.register_behavior(P+'noop',lambda c:())
    r.register_behavior(BOLT,lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),))
    r.register_behavior(FIVE,lambda c:(Draw(c.player_id,1),))
    definitions=(CardDefinition(ZERO,ZERO,CardType.SPELL,on_play=P+'noop',metadata=META),
        CardDefinition(BOLT,BOLT,CardType.SPELL,cost=2,on_play=BOLT,metadata=META,
            targeting=TargetSpec(kinds=(CardType.HERO,),relation='enemy')),
        CardDefinition(FIVE,FIVE,CardType.SPELL,cost=5,on_play=FIVE,metadata=META),
        CardDefinition(FOREIGN,FOREIGN,CardType.SPELL,cost=3,on_play=P+'noop',metadata=replace(META,classes=(CardClass.ROGUE,))),
        CardDefinition(HIDDEN,HIDDEN,CardType.SPELL,cost=3,on_play=P+'noop',metadata=replace(META,collectible=False)))
    for d in definitions:r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    members=[ZERO,BOLT,FIVE,FOREIGN,HIDDEN]
    if mode=='unknown':
        r.register_pool_card(PoolCard.from_definition(CardDefinition(GHOST,GHOST,CardType.SPELL,on_play=P+'noop',metadata=META)))
        members.append(GHOST)
    r.register_pool(PoolDefinition('constructed.cards','fixture-v1','local-2026-09-23','experimental',tuple(PoolMember(x)for x in members)))
    def held(c):return next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==WEAPON)
    scripts={COPY:lambda c:(CopyCard(CardReference.capture(held(c)),c.player_id,mode='current',source_id=c.source_id),),
        BASE:lambda c:(CopyCard(CardReference.capture(held(c)),c.player_id,mode='base',source_id=c.source_id),),
        RESET:lambda c:(MoveCard(CardReference.capture(held(c)),c.player_id,Zone.HAND,reset=True,source_id=c.source_id),),
        DECK:lambda c:(MoveCard(CardReference.capture(held(c)),c.player_id,Zone.DECK,'top',source_id=c.source_id),Draw(c.player_id,1)),
        DISCOUNT:lambda c:(ModifyStoredCost(CardReference.capture(held(c)),CostSpec(delta=-1),c.source_id),),
        ALTER:lambda c:(TransformStoredCard(CardReference.capture(held(c)),UNIT,c.source_id),),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid==KILL else None,metadata=META))
    def fail(c):raise ResolutionError('Deliberate original Hammer continuation failure')
    r.register_behavior(P+'fail',fail)
    if mode in ('creation-wait','creation-fail','attack-wait','cast-wait'):
        event='card_added_to_hand'if mode.startswith('creation')else 'attack_finished'if mode=='attack-wait'else 'spell_cast_started'
        def watch(c):
            if c.event.player_id not in (None,c.player_id):return ()
            if mode.startswith('creation'):
                if c.event.target_id is None or c.state.entities[c.event.target_id].card_id!=WEAPON:return ()
            elif mode=='cast-wait':
                row=c.state.cast_history[dict(c.event.data)['cast_id']-1]
                if row.caster_id is None or c.state.entities[row.caster_id].card_id!=WEAPON:return ()
            else:
                if c.event.source_id!=c.state.players[c.player_id].hero_id:return ()
            if mode=='creation-fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            options=[ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))]
            if mode=='attack-wait':
                wid=c.state.players[c.player_id].weapon_id
                if wid is not None:options.append(ChoiceOption('break','Break original weapon',(ModifyWeapon(wid,durability=-10,source_id=c.source_id),)))
            return (RequestChoice(3-c.player_id,tuple(options),c.source_id),)
        r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=3,
            metadata=META,triggers=(TriggerSpec(event,WATCH),)))
    r.validate();r.freeze();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
    return s


class ArchaedasTests(unittest.TestCase):
    def game(self,hand=None,mode='normal',pid=1):
        self.mode,self.pid=mode,pid
        return Game.from_scenario(Scenario(tuple(PlayerSetup(HERO,hand=((CARD,)if hand is None else hand)if p==pid else (),
            board=(WATCH,)if p==pid and mode in('creation-wait','creation-fail','attack-wait','cast-wait')else (),
            deck=(UNIT,)*16,mana=50,max_mana=50,mana_cap=50)for p in (1,2)),active_player=pid,seed=388,
            generation_context=GenerationContext('local-2026-09-23','experimental')),registry(mode))
    def play(self,g,cid=CARD,target=None):
        e=next(g.state.entities[i]for i in g.state.players[self.pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(self.pid,e.id,target_id=target,position=len(g.state.players[self.pid].board)if e.kind==CardType.MINION else None));return e.id
    def select_card(self,g,cid=BOLT):
        q=g.state.pending_choice;option=next(x for x in q.options if x.card_id==cid)
        g.apply(SelectChoice(q.player_id,q.id,(option.id,)))
    def select(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def hand_weapons(self,g):return [g.state.entities[i]for i in g.state.players[self.pid].hand if g.state.entities[i].card_id==WEAPON]
    def obtain(self,g,cid=BOLT):self.play(g);self.select_card(g,cid);return self.hand_weapons(g)[0].id
    def equip(self,g,cid=BOLT):self.obtain(g,cid);return self.play(g,WEAPON)
    def attack(self,g):g.apply(Attack(self.pid,g.state.players[self.pid].hero_id,g.state.players[3-self.pid].hero_id))
    def cycle(self,g):g.apply(EndTurn(self.pid));g.apply(EndTurn(3-self.pid))
    def portable(self,g):
        reader=registry(self.mode,'reader');self.assertIsNot(reader,g.registry)
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,reader)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return other

    def test_both_real_records_four_complete_primary_faces_and_pinned_live_name_display(self):
        pack=load_batch();rows={x['record']['id']:x['record']for k in ('cards','dependencies')for x in pack[k]}
        self.assertEqual(pack['parent_child_dbf_ids'],[132338]);self.assertTrue(pack['dependency_assignment_primary_confirmed'])
        for face in pack['official_observations']:
            check_face(rows[face['card_id']],face['face'],face['locale'],pack['display_normalizations'].get(face['card_id']))
        face=next(x for x in pack['official_observations']if x['card_id']==WEAPON)
        with self.assertRaises(ValueError):check_face(rows[WEAPON],face['face'],face['locale'])
        bad=deepcopy(rows[WEAPON]);bad['text']+='额外效果'
        with self.assertRaises(ValueError):check_face(bad,face['face'],face['locale'],{'{0}':''})

    def test_actual_battlecry_offers_only_current_class_collectible_spells(self):
        g=self.game();self.play(g);q=g.state.pending_choice
        self.assertEqual({x.card_id for x in q.options},{ZERO,BOLT,FIVE});self.assertEqual(g.state.players[1].mana,46)
        self.assertFalse(self.hand_weapons(g));self.portable(g)

    def test_genuine_spell_discovery_materializes_real_weapon_with_same_cost_and_native_spell(self):
        for spell,cost in ((ZERO,0),(BOLT,2),(FIVE,5)):
            g=self.game();wid=self.obtain(g,spell);weapon=g.state.entities[wid]
            self.assertEqual((weapon.card_id,weapon.kind,weapon.attack,weapon.durability,weapon.base_cost),(WEAPON,CardType.WEAPON,3,3,cost))
            self.assertEqual(weapon_material(weapon)[1],spell)
            record=g.state.card_discovery_history[-1];self.assertEqual(record.result.selected[0].card_id,spell)
            self.assertFalse(g.state.cast_history)
        self.portable(g)

    def test_real_weapon_play_uses_selected_spell_cost_not_template_one(self):
        for spell,cost in ((ZERO,0),(BOLT,2),(FIVE,5)):
            g=self.game();wid=self.equip(g,spell)
            self.assertEqual((g.state.players[1].weapon_id,g.state.players[1].mana),(wid,46-cost))
            self.assertEqual(g.state.play_history[-1].cost,cost);self.assertFalse(g.state.cast_history)
        self.portable(g)

    def test_actual_hero_attack_casts_original_spell_without_new_hand_payment(self):
        g=self.game();wid=self.equip(g);mana=g.state.players[1].mana;self.attack(g)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,25)
        self.assertEqual((len(g.state.cast_history),len(g.state.play_history),g.state.players[1].mana),(1,2,mana))
        self.assertEqual((g.state.cast_history[-1].card_id,g.state.cast_history[-1].caster_id),(BOLT,wid));self.portable(g)

    def test_final_durability_swing_still_casts_once_then_weapon_is_destroyed(self):
        g=self.game();wid=self.equip(g)
        for i in range(3):
            if i:self.cycle(g)
            self.attack(g)
        self.assertEqual(len(g.state.cast_history),3);self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(g.state.entities[wid].zone,Zone.GRAVEYARD);self.portable(g)

    def test_source_creator_death_does_not_remove_native_weapon_spell(self):
        g=self.game(hand=(CARD,KILL));source=self.play(g);self.select_card(g)
        self.play(g,KILL,source);self.play(g,WEAPON);self.attack(g)
        self.assertEqual(g.state.cast_history[-1].card_id,BOLT)

    def test_current_and_base_hand_copies_preserve_native_spell_and_original_cost(self):
        for operation in (COPY,BASE):
            g=self.game(hand=(CARD,operation));self.obtain(g,FIVE);self.play(g,operation)
            self.assertEqual([x.base_cost for x in self.hand_weapons(g)],[5,5])
            self.assertEqual([weapon_material(x)[1]for x in self.hand_weapons(g)],[FIVE,FIVE]);self.portable(g)

    def test_normal_reset_and_deck_reentry_preserve_native_spell_material(self):
        for operation in (RESET,DECK):
            g=self.game(hand=(CARD,operation));wid=self.obtain(g,FIVE);self.play(g,operation)
            weapon=g.state.entities[wid];self.assertEqual((weapon.zone,weapon.base_cost),(Zone.HAND,5))
            self.assertEqual(weapon_material(weapon)[1],FIVE);self.portable(g)

    def test_later_local_discount_changes_payment_without_replacing_native_original_cost(self):
        g=self.game(hand=(CARD,DISCOUNT));self.obtain(g,FIVE);self.play(g,DISCOUNT);self.play(g,WEAPON)
        self.assertEqual(g.state.play_history[-1].cost,4);self.assertEqual(g.state.entities[g.state.players[1].weapon_id].base_cost,5)

    def test_explicit_stored_replacement_discards_old_spell_material(self):
        g=self.game(hand=(CARD,ALTER));wid=self.obtain(g);self.play(g,ALTER)
        self.assertEqual(g.state.entities[wid].card_id,UNIT);self.assertIsNone(weapon_material(g.state.entities[wid]));self.portable(g)

    def test_materialized_hand_event_wait_has_complete_spell_cost_and_restores(self):
        g=self.game(mode='creation-wait');self.obtain(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.hand_weapons(g)[0].base_cost,2);other=self.portable(g)
        for match in (g,other):self.select(match)
        self.assertEqual(g.snapshot(),other.snapshot())

    def test_accepted_attack_wait_restores_and_keeps_one_original_cast(self):
        g=self.game(mode='attack-wait');self.equip(g);self.attack(g);self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g)
        for match in (g,other):self.select(match)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.cast_history),1)

    def test_accepted_attack_trigger_keeps_original_spell_after_weapon_break_reaction(self):
        g=self.game(mode='attack-wait');self.equip(g);self.attack(g);self.select(g,'break')
        self.assertEqual(len(g.state.cast_history),1);self.assertEqual(g.state.cast_history[-1].card_id,BOLT);self.portable(g)

    def test_actual_automatic_cast_reaction_wait_restores_without_extra_attack_or_cast(self):
        g=self.game(mode='cast-wait');self.equip(g);self.attack(g);self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g)
        for match in (g,other):self.select(match)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.cast_history),1)

    def test_creation_failure_rolls_back_original_selection_and_materialization(self):
        g=self.game(mode='creation-fail');self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.select_card(g)
        self.assertEqual(g.snapshot(),before)

    def test_late_attack_choice_failure_preserves_accepted_attack_and_original_weapon(self):
        g=self.game(mode='attack-wait');self.equip(g);self.attack(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.select(g,'fail')
        self.assertEqual(g.snapshot(),before);self.select(g);self.assertEqual(len(g.state.cast_history),1)

    def test_unknown_eligible_spell_fails_before_offer_and_rolls_back_payment_and_rng(self):
        g=self.game(mode='unknown');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'ghost'):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_weapon_discovery_rejects_unrelated_query_multiple_rounds_and_other_delivery(self):
        for values in ({'query':PoolQuery(kinds=(CardType.MINION,))},{'discoveries':2},{'destination':'deck'},
                {'count':2},{'cost':CostSpec(delta=-1)}):
            args=dict(player_id=1,pool_id='constructed.cards',query=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current'),
                source_id=1,spell_weapon_card_id=WEAPON);args.update(values)
            with self.assertRaises(ValueError):DiscoverFromPool(**args)

    def test_rehashed_native_weapon_cannot_lose_spell_or_change_innate_cost(self):
        g=self.game();wid=self.obtain(g);saved=g.snapshot()
        for kind in ('spell','cost'):
            bad=deepcopy(saved);entity=bad['state']['entities'][str(wid)]
            if kind=='cost':entity['base_cost']=7
            else:
                row=next(x for x in entity['abilities']if x['carved_spell_id']is not None);row['carved_spell_id']=None
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry(self.mode,'reader'))

    def test_public_equipped_spell_and_private_owner_hand_do_not_leak_to_opponent(self):
        g=self.game();self.obtain(g)
        own=g.for_player(1).observe();enemy=g.for_player(2).observe()
        self.assertIn('cast_card_id',json.dumps(own));self.assertNotIn('cast_card_id',json.dumps(enemy))
        self.play(g,WEAPON)
        for pid in(1,2):
            observed=g.for_player(pid).observe()['observation'];self.assertEqual(observed['players'][0]['weapon']['cast_card_id'],BOLT)
            visible=json.dumps(observed)+json.dumps(g.player_events(pid))
            for key in ('spell_weapon_card_id','carved_spell_id','resolution_frame','rng_state'):
                self.assertNotIn('"'+key+'"',visible)

    def test_other_seat_keeps_original_weapon_owner_spell_and_payment(self):
        g=self.game(pid=2);self.equip(g);self.attack(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,25)
        self.assertEqual(g.state.cast_history[-1].player_id,2);self.portable(g)


if __name__=='__main__':unittest.main()
