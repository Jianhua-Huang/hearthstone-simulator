"""Three complete native Kindred bodies using unchanged own-turn primitives."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    DamageKind, EndTurn, Game, IllegalAction, IntrinsicCostSpec, PlayCard,
    PlayerSetup, Rarity, Registry, ResolutionError, Scenario, SelectChoice,
    SnapshotError, SpellSchool, TargetSpec, TriggerSpec, Zone,
    query_for_definition, query_previous_owner_turn)
from hs_sim.engine.costs import capture_cost_input, capture_quote_fact
from hs_sim.engine.effects import (ChoiceOption, CopyMinion, Damage, Draw,
    InvokeBehavior, RequestChoice, Summon, Transform)
from hs_sim.engine.interrupts import CounterMinion, CounterSpell
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1]
PIN='d1a20c2e2992ff5c1316e29c3f74cba89a2e8558b95dc42009507ec9155ac1d7'
MINION='DINO_435'; FROST='TLC_440'; HOLY='TLC_816'


def evidence():
    packet=json.loads((ROOT/'data/support/kindred-basics.json').read_bytes())
    if canonical_digest(packet)!=PIN: raise ValueError('Complete native Kindred evidence changed')
    return packet


def meta(tribes=(), *, collectible=True):
    return CardMetadata(collectible,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=tribes)


def registry():
    r=Registry('kindred-independent-basics-v1')
    raw={c['id']:c for c in evidence()['records']}
    r.register_card(CardDefinition('kr.hero','Hero',CardType.HERO,health=30,metadata=meta(collectible=False)))
    for cid,tribes in (('kr.dragon',('dragon',)),('kr.beast',('beast',)),
            ('kr.empty',()),('kr.unknown',None),('kr.hidden',())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=8,metadata=meta(tribes)))
    r.register_behavior('kr.cb.nothing',lambda c: ())
    for cid,school in (('kr.frost',SpellSchool.FROST),('kr.holy',SpellSchool.HOLY),
            ('kr.fire',SpellSchool.FIRE),('kr.unschooled',None)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play='kr.cb.nothing',
            spell_school=school,metadata=meta()))

    def matched(c,cid):
        return query_previous_owner_turn(c.state,c.player_id,query_for_definition(r.card(cid))).matched
    r.register_behavior('kr.cb.native.copy',lambda c:
        (CopyMinion(c.source_id,c.player_id),) if matched(c,MINION) else ())
    r.register_behavior('kr.cb.native.frost',lambda c:
        (Damage(c.target_id,4,c.source_id,DamageKind.SPELL),Draw(c.player_id,1,c.source_id),
         *((Draw(c.player_id,1,c.source_id),) if matched(c,FROST) else ())))
    r.register_behavior('kr.cb.native.holy',lambda c: (Draw(c.player_id,2,c.source_id),))
    row=raw[MINION]
    # Raw CARDRACE 26 is All; the production representative parser's fixed
    # reviewed race map is intentionally not broadened for an isolated adapter.
    r.register_card(CardDefinition(MINION,row['name'],CardType.MINION,cost=row['cost'],
        attack=row['attack'],health=row['health'],on_play='kr.cb.native.copy',
        metadata=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.EPIC,deck_identity=MINION,tribes=('all',))))
    row=raw[FROST]
    r.register_card(CardDefinition(FROST,row['name'],CardType.SPELL,cost=row['cost'],
        on_play='kr.cb.native.frost',spell_school=SpellSchool.FROST,
        targeting=TargetSpec(),metadata=metadata_from_record(row)))
    row=raw[HOLY]
    r.register_card(CardDefinition(HOLY,row['name'],CardType.SPELL,cost=row['cost'],
        on_play='kr.cb.native.holy',spell_school=SpellSchool.HOLY,
        intrinsic_costs=(IntrinsicCostSpec(delta=-2),),metadata=metadata_from_record(row)))

    def fail(c): raise ResolutionError('Deliberate native Kindred boundary rollback')
    r.register_behavior('kr.cb.fail',fail)
    def wait(c):
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),
            ChoiceOption('bad','Fail',(InvokeBehavior('kr.cb.fail',c.source_id,c.player_id),)),
        ),c.source_id),)
    r.register_behavior('kr.cb.wait-commit',lambda c: wait(c)
        if c.play is not None and c.play.card_id in (MINION,HOLY) else ())
    r.register_behavior('kr.cb.wait-health',lambda c: wait(c)
        if c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==FROST else ())
    r.register_behavior('kr.cb.counter-primer',lambda c:
        (CounterMinion(dict(c.event.data)['window_id']),) if c.play is not None and c.play.card_id=='kr.dragon'
        else (CounterSpell(dict(c.event.data)['window_id']),) if c.play is not None and c.play.card_id=='kr.frost' else ())
    r.register_behavior('kr.cb.counter-native',lambda c:
        (CounterSpell(dict(c.event.data)['window_id']),) if c.play is not None and c.play.card_id==FROST else ())
    for name,event,body in (('wait-commit','card_committed','kr.cb.wait-commit'),
            ('wait-health','health_resolved','kr.cb.wait-health'),
            ('counter-primer','card_committed','kr.cb.counter-primer'),
            ('counter-native','card_committed','kr.cb.counter-native')):
        r.register_card(CardDefinition('kr.watch.'+name,name,CardType.MINION,health=8,
            metadata=meta(),triggers=(TriggerSpec(event,body),)))
    r.register_behavior('kr.cb.transform',lambda c: (Transform(c.target_id,'kr.empty'),))
    r.register_card(CardDefinition('kr.transform','Transform fixture',CardType.SPELL,
        on_play='kr.cb.transform',targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),metadata=meta()))
    r.register_behavior('kr.cb.other-sources',lambda c:
        (Summon(c.player_id,MINION),CastSpell(c.player_id,'kr.frost')))
    r.register_card(CardDefinition('kr.other-sources','Other source fixture',CardType.SPELL,
        on_play='kr.cb.other-sources',metadata=meta()))
    r.register_behavior('kr.cb.copy-native',lambda c: (CopyMinion(c.target_id,c.player_id),))
    r.register_card(CardDefinition('kr.copy-native','Copy fixture',CardType.SPELL,
        on_play='kr.cb.copy-native',targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),metadata=meta()))
    return r


class KindredBasicTests(unittest.TestCase):
    def game(self,hand=(),*,enemy_hand=(),board=(),enemy_board=(),active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('kr.hero',hand=hand,board=board,deck=('kr.empty',)*12,max_mana=10,mana=10),
            PlayerSetup('kr.hero',hand=enemy_hand,board=enemy_board,deck=('kr.empty',)*12,max_mana=10,mana=10)),
            active_player=active,seed=106),registry())
    def play(self,g,cid,*,target=None):
        p=g.state.active_player
        source=next(e for e in g.state.players[p].hand if g.state.entities[e].card_id==cid)
        pos=len(g.state.players[p].board) if g.registry.card(cid).kind==CardType.MINION else None
        g.apply(PlayCard(p,source,target,pos)); return source
    def end(self,g): g.apply(EndTurn(g.state.active_player))
    def next_own(self,g): self.end(g); self.end(g)
    def choose(self,g,key='ok'):
        choice=g.state.pending_choice;g.apply(SelectChoice(choice.player_id,choice.id,(key,)))
    def query(self,g,cid,player=1):
        return query_previous_owner_turn(g.state,player,query_for_definition(g.registry.card(cid)))
    def cost(self,g,cid=HOLY,player=1):
        e=next(g.state.entities[i] for i in g.state.players[player].hand if g.state.entities[i].card_id==cid)
        return capture_quote_fact(g.state,g.registry,capture_cost_input(e))
    def copies(self,g,player=1):
        return [g.state.entities[e] for e in g.state.players[player].board if g.state.entities[e].card_id==MINION]
    def draws(self,g,source): return [x for x in g.state.draw_history if x.source_id==source]
    def check(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        variants=(Game.from_snapshot(saved,registry()),g.clone(),replay(build_replay(g),registry()))
        for other in variants:self.assertEqual(other.snapshot(),saved)
        return variants

    def test_complete_native_raw_pin_three_full_bodies_and_metadata(self):
        packet=evidence();raw={c['id']:c for c in json.loads((ROOT/'data/extracted/cards.json').read_bytes())}
        self.assertEqual((len(packet['records']),packet['executable_representatives']),(31,[MINION,FROST,HOLY]))
        for row in packet['records']:self.assertEqual(row,raw[row['id']])
        r=registry();m,f,h=(r.card(i) for i in (MINION,FROST,HOLY))
        self.assertEqual((m.cost,m.attack,m.health,m.metadata.tribes,raw[MINION]['tags']['CARDRACE']),(5,3,4,('all',),26))
        self.assertIsNone(m.battlecry);self.assertIsNone(m.deathrattle)
        self.assertEqual((f.cost,f.spell_school,f.metadata.classes,f.metadata.runes.frost),(4,SpellSchool.FROST,(CardClass.DEATH_KNIGHT,),2))
        self.assertEqual((h.cost,h.spell_school,h.metadata.classes,h.intrinsic_costs),(4,SpellSchool.HOLY,(CardClass.PRIEST,),(IntrinsicCostSpec(delta=-2),)))
        self.assertTrue(all(i not in r.cards for i in packet['evidence_only']))

    def test_initial_board_or_current_turn_minion_does_not_activate_native_copy(self):
        g=self.game(('kr.dragon',MINION),board=('kr.beast',))
        self.play(g,'kr.dragon');self.assertFalse(self.query(g,MINION).matched)
        self.play(g,MINION);self.assertEqual(len(self.copies(g)),1);self.assertFalse(g.state.battlecry_history)

    def test_previous_matching_minion_native_copy_is_single_on_play_bonus(self):
        g=self.game(('kr.dragon','kr.beast',MINION));self.play(g,'kr.dragon');self.play(g,'kr.beast');self.next_own(g)
        q=self.query(g,MINION);self.assertEqual([x.matched for x in q.rows],[True,True])
        source=self.play(g,MINION);self.assertEqual([(e.attack,e.health) for e in self.copies(g)],[(3,4),(3,4)])
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(5,5))
        self.assertEqual(sum(p.card_id==MINION for p in g.state.play_history),1)
        self.assertEqual(g.state.play_history[-1].source_id,source);self.assertFalse(g.state.battlecry_history);self.check(g)

    def test_all_tribe_does_not_match_known_tribeless_previous_minion(self):
        g=self.game(('kr.empty',MINION));self.play(g,'kr.empty');self.next_own(g)
        self.assertEqual([x.matched for x in self.query(g,MINION).rows],[False])
        self.play(g,MINION);self.assertEqual(len(self.copies(g)),1)

    def test_summoning_or_copying_native_minion_does_not_execute_on_play_bonus(self):
        g=self.game(('kr.dragon','kr.other-sources','kr.copy-native'));self.play(g,'kr.dragon');self.next_own(g)
        self.play(g,'kr.other-sources');self.assertEqual(len(self.copies(g)),1)
        source=self.copies(g)[0].id;self.play(g,'kr.copy-native',target=source)
        self.assertEqual(len(self.copies(g)),2);self.assertFalse(any(p.card_id==MINION for p in g.state.play_history));self.check(g)

    def test_latest_empty_own_interval_supersedes_older_matching_minion(self):
        g=self.game(('kr.dragon',MINION));self.play(g,'kr.dragon');self.next_own(g)
        self.assertTrue(self.query(g,MINION).matched);self.next_own(g)
        q=self.query(g,MINION);self.assertEqual((q.owner_turn.owner_index,q.rows,q.matched),(2,(),False))
        self.play(g,MINION);self.assertEqual(len(self.copies(g)),1)

    def test_opponent_play_does_not_prime_current_players_native_minion(self):
        g=self.game((MINION,),enemy_hand=('kr.dragon',));self.end(g);self.play(g,'kr.dragon');self.end(g)
        self.assertFalse(self.query(g,MINION).matched);self.play(g,MINION);self.assertEqual(len(self.copies(g)),1)

    def test_later_transform_cannot_rewrite_previous_frozen_minion_type(self):
        g=self.game(('kr.dragon','kr.transform',MINION));source=self.play(g,'kr.dragon')
        self.play(g,'kr.transform',target=source);self.assertEqual(g.registry.card(g.state.entities[source].card_id).metadata.tribes,())
        self.next_own(g);q=self.query(g,MINION)
        self.assertEqual(q.rows[0].face.metadata.tribes,('dragon',));self.assertTrue(q.matched)
        self.play(g,MINION);self.assertEqual(len(self.copies(g)),2);self.check(g)

    def test_native_frost_base_damage_and_draw_without_previous_match(self):
        g=self.game((FROST,));target=g.state.players[2].hero_id;source=self.play(g,FROST,target=target)
        self.assertEqual((g.state.entities[target].health,len(self.draws(g,source)),g.state.play_history[-1].cost),(26,1,4));self.check(g)

    def test_native_frost_any_previous_matching_play_adds_one_draw(self):
        g=self.game(('kr.fire','kr.frost','kr.holy',FROST))
        for cid in ('kr.fire','kr.frost','kr.holy'):self.play(g,cid)
        self.next_own(g);q=self.query(g,FROST)
        self.assertEqual([x.matched for x in q.rows],[False,True,False])
        source=self.play(g,FROST,target=g.state.players[2].hero_id)
        self.assertEqual(len(self.draws(g,source)),2);self.assertEqual(g.state.players[1].mana,6);self.check(g)

    def test_same_turn_school_and_previous_other_kind_do_not_prime_native_frost(self):
        g=self.game(('kr.dragon','kr.frost',FROST));self.play(g,'kr.dragon');self.next_own(g);self.play(g,'kr.frost')
        self.assertEqual(self.query(g,FROST).rows,());source=self.play(g,FROST,target=g.state.players[2].hero_id)
        self.assertEqual(len(self.draws(g,source)),1)

    def test_previous_generated_cast_or_summon_is_not_a_hand_play(self):
        g=self.game(('kr.other-sources',FROST));self.play(g,'kr.other-sources');self.next_own(g)
        self.assertEqual([x.face.card_id for x in self.query(g,FROST).rows],['kr.other-sources'])
        self.assertFalse(self.query(g,FROST).matched);self.assertEqual([x.origin for x in g.state.cast_history],['hand','effect'])
        source=self.play(g,FROST,target=g.state.players[2].hero_id);self.assertEqual(len(self.draws(g,source)),1)

    def test_native_holy_cost_reuses_original_intrinsic_condition_and_paid_root(self):
        g=self.game(('kr.holy',HOLY));self.assertEqual(self.cost(g).amount,4)
        self.play(g,'kr.holy');self.next_own(g);fact=self.cost(g);condition=fact.intrinsic.condition_facts[0]
        self.assertEqual((condition.query.spell_school,condition.matched,fact.amount),(SpellSchool.HOLY,True,2))
        source=self.play(g,HOLY);self.assertEqual((g.state.players[1].mana,g.state.play_history[-1].cost,len(self.draws(g,source))),(8,2,2));self.check(g)

    def test_native_holy_current_school_or_different_previous_school_keeps_base_price(self):
        g=self.game(('kr.frost','kr.holy',HOLY));self.play(g,'kr.frost');self.next_own(g);self.play(g,'kr.holy')
        self.assertFalse(self.cost(g).intrinsic.condition_facts[0].matched);self.assertEqual(self.cost(g).amount,4)
        source=self.play(g,HOLY);self.assertEqual((g.state.play_history[-1].cost,len(self.draws(g,source))),(4,2))

    def test_multiple_previous_holy_cards_apply_one_boolean_discount(self):
        g=self.game(('kr.holy','kr.holy',HOLY));self.play(g,'kr.holy');self.play(g,'kr.holy');self.next_own(g)
        q=self.cost(g).intrinsic.condition_facts[0];self.assertEqual([x.matched for x in q.rows],[True,True])
        self.assertEqual(self.cost(g).amount,2)

    def test_unknown_previous_minion_after_true_row_fails_and_rolls_back_native_play(self):
        g=self.game(('kr.dragon','kr.unknown',MINION));self.play(g,'kr.dragon');self.play(g,'kr.unknown');self.next_own(g)
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,MINION)
        self.assertEqual(g.snapshot(),saved)
        with self.assertRaisesRegex(ValueError,'known Minion tribes'):self.query(g,MINION)

    def test_countered_paid_primer_still_counts_as_played_for_each_native_kind(self):
        for primer,native in (('kr.dragon',MINION),('kr.frost',FROST)):
            with self.subTest(native=native):
                g=self.game((primer,native),board=('kr.watch.counter-primer',));self.play(g,primer);self.next_own(g)
                self.assertTrue(self.query(g,native).matched)
                source=self.play(g,native,target=g.state.players[2].hero_id if native==FROST else None)
                self.assertEqual(len(self.copies(g)) if native==MINION else len(self.draws(g,source)),2);self.check(g)

    def test_countered_native_frost_retains_payment_without_base_or_bonus_draw(self):
        g=self.game(('kr.frost',FROST),board=('kr.watch.counter-native',));self.play(g,'kr.frost');self.next_own(g)
        source=self.play(g,FROST,target=g.state.players[2].hero_id)
        self.assertEqual((g.state.players[1].mana,len(self.draws(g,source)),g.state.entities[g.state.players[2].hero_id].health),(6,0,30))
        self.assertEqual(g.state.play_history[-1].played_face.card_id,FROST);self.check(g)

    def test_native_minion_committed_wait_restore_clone_and_replay_use_one_root(self):
        g=self.game(('kr.dragon',MINION),board=('kr.watch.wait-commit',));self.play(g,'kr.dragon');self.next_own(g)
        source=self.play(g,MINION);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.entities[source].zone,Zone.PLAY)
        saved=g.snapshot();variants=self.check(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for other in (g,*variants):
            self.choose(other);self.assertEqual((len(self.copies(other)),len(other.state.play_history),other.state.players[1].mana),(2,2,5))
        self.check(g)

    def test_native_frost_health_wait_retains_bonus_and_failed_selection_is_atomic(self):
        g=self.game(('kr.frost',FROST),board=('kr.watch.wait-health',));self.play(g,'kr.frost');self.next_own(g)
        source=self.play(g,FROST,target=g.state.players[2].hero_id);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(self.draws(g,source)),0);saved=g.snapshot();variants=self.check(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for other in (g,*variants):self.choose(other);self.assertEqual(len(self.draws(other,source)),2)
        self.check(g)

    def test_native_holy_committed_wait_keeps_frozen_discount_and_single_payment(self):
        g=self.game(('kr.holy',HOLY),board=('kr.watch.wait-commit',));self.play(g,'kr.holy');self.next_own(g)
        source=self.play(g,HOLY);self.assertEqual((g.state.players[1].mana,g.state.play_history[-1].cost),(8,2))
        saved=g.snapshot();variants=self.check(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for other in (g,*variants):
            self.choose(other);self.assertEqual((other.state.players[1].mana,len(self.draws(other,source)),len(other.state.play_history)),(8,2,2))
        self.check(g)

    def test_read_only_condition_and_cost_quotes_leave_state_rng_and_events_unchanged(self):
        g=self.game(('kr.holy',HOLY,MINION));self.play(g,'kr.holy');self.next_own(g);saved=g.snapshot()
        for _ in range(3):self.assertTrue(self.query(g,HOLY).matched);self.assertEqual(self.cost(g).amount,2)
        self.assertFalse(self.query(g,MINION).matched);self.assertEqual(g.snapshot(),saved)

    def test_player_port_has_effective_price_without_frozen_history_or_hidden_cards(self):
        g=self.game(('kr.holy',HOLY),enemy_hand=('kr.hidden',));self.play(g,'kr.holy');self.next_own(g)
        row=next(x for x in g.observe(1)['players'][0]['hand'] if x['card_id']==HOLY)
        self.assertEqual(row['cost']['amount'],2);port=g.for_player(1);dto=port.legal_actions()
        action=next(a for a in dto['actions'] if a.get('card')==row['ref'])
        self.assertTrue(port.submit({'revision':dto['revision'],'action':action})['accepted'])
        self.assertEqual(g.state.play_history[-1].cost,2)
        self.assertNotIn('kr.hidden',json.dumps(port.observe()))
        for player in (1,2):
            wire=json.dumps((g.for_player(player).observe(),g.for_player(player).legal_actions()))
            for field in ('played_face','owner_turn_history','condition_facts','history_profile_id'):self.assertNotIn(field,wire)
        self.check(g)

    def test_rehashed_snapshot_cannot_rewrite_native_priming_face_school(self):
        g=self.game(('kr.holy',HOLY),board=('kr.watch.wait-commit',));self.play(g,'kr.holy');self.next_own(g);self.play(g,HOLY)
        bad=deepcopy(g.snapshot());bad['state']['play_history'][0]['played_face']['spell_school']='fire'
        bad['state_hash']=canonical_hash({k:v for k,v in bad.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as raised:Game.from_snapshot(bad,registry())
        self.assertNotIn('digest mismatch',str(raised.exception));self.check(g)


if __name__=='__main__':unittest.main()
