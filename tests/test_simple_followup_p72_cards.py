"""Native private Void, original Mech recipients and real named summon bodies."""
from dataclasses import asdict
from functools import lru_cache
import hashlib,json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p72_cards as cards
from hs_sim.cards.simple_followup_p72_cards import (IRIDA,GLOW,MINIBOT,COBALT,SHOTBOT,MUMMY,BUBBLE,
    EGG,ROBOSAUR,SKY,COPTER,BUSY,ROOTS,VOID,PREFIX,load_batch,register_simple_followup_p72_cards)
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,
    PlayerSetup,PlayCard,Rarity,Registry,Scenario,SelectChoice,TargetSpec,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,
    InvokeBehavior,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import BoardPresenceReference,DamageKind,LimitedTriggerSpec,SummonQuantitySpec
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.zones import AddToDeck,CardReference

TEST='p72.test.'
HERO,HP,MECH,ALL,BEAST,FILLER,DOUBLE,WATCH=(TEST+i for i in('hero','power','mech','all','beast','filler','double','watch'))
KILL,BOUNCE,SILENCE,STEAL,CHANGE,COPY,HIT,FILL,DECKBUFF,APPEND,DORMANT=(TEST+i for i in
    ('kill','bounce','silence','steal','change','copy','hit','fill','deckbuff','append','dormant'))
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()


def meta(tribes=(),collectible=True,cls=CardClass.NEUTRAL):
    return CardMetadata(collectible,(cls,),Rarity.COMMON if collectible else None,tribes=tribes)


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    present=tuple(cid in r.cards for cid in ROOTS)
    if not any(present):register_simple_followup_p72_cards(r)
    elif not all(present):raise AssertionError('P72 requires its complete assigned assembly')
    register_candidate_pool_metadata(r);r.validate();return r


def registry(mode=None):
    r=Registry('p72-small-native-fixtures');register_simple_followup_p72_cards(r)
    r.register_behavior(TEST+'nop',lambda c:())
    r.register_card(CardDefinition(HP,HP,CardType.HERO_POWER,cost=2,on_use=TEST+'nop',metadata=meta(collectible=False,cls=CardClass.PALADIN)))
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,initial_hero_power=HP,metadata=meta(collectible=False,cls=CardClass.PALADIN)))
    for cid,atk,hp,tribes in((MECH,1,3,('mech',)),(ALL,1,4,('all',)),(BEAST,2,12,('beast',)),(FILLER,0,1,())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=atk,health=hp,metadata=meta(tribes)))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=30,summon_quantities=(SummonQuantitySpec(2),),metadata=meta()))
    def reenter(c):return(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),1),)
    def fail(c):raise ResolutionError('P72 deliberate continuation failure')
    r.register_behavior(TEST+'reenter',reenter);r.register_behavior(TEST+'fail',fail)
    bodies={KILL:lambda c:(Destroy(c.target_id,c.source_id),),BOUNCE:lambda c:(ReturnToHand(c.target_id),),
        SILENCE:lambda c:(Silence(c.target_id),),STEAL:lambda c:(ChangeControl(c.target_id,2),),
        CHANGE:lambda c:(Transform(c.target_id,MECH),),COPY:lambda c:(CopyMinion(
            BoardPresenceReference.capture(c.state,c.target_id),1,cause=cards.SummonCause.capture(c)),),
        HIT:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        FILL:lambda c:tuple(AddToHand(1,FILLER,c.source_id)for _ in range(10)),
        DECKBUFF:lambda c:tuple(BuffStoredCard(CardReference.capture(c.state.entities[i]),2,3,c.source_id)for i in c.state.players[1].deck),
        APPEND:lambda c:(AddToDeck(1,MECH,source_id=c.source_id),AddToDeck(1,MECH,source_id=c.source_id)),
        DORMANT:lambda c:(MakeDormant(c.target_id,3,c.source_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            targeting=TargetSpec()if cid in(KILL,BOUNCE,SILENCE,STEAL,CHANGE,COPY,HIT,DORMANT)else None,metadata=meta()))
    if mode:
        event={'void':'card_moved_to_hand','bubble':'ability_granted','cobalt':'minion_summoned','sky':'minion_summoned','busy':'stats_changed'}[mode]
        def eligible(c):
            if mode=='void':return c.event.player_id==1 and c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==IRIDA
            target=c.state.entities.get(c.event.target_id)
            if target is None or target.controller!=1:return False
            if mode=='bubble':return target.card_id==MECH and dict(c.event.data).get('ability_kind')=='keyword'
            if mode=='cobalt':return target.card_id==MINIBOT
            if mode=='sky':return target.card_id==COPTER
            return target.card_id==MECH
        def pause(c):
            effects=()
            if mode=='void':
                e=c.state.entities[c.event.source_id]
                effects=(RemoveFromGame((MinionReference.capture(e),),c.source_id),)
            elif mode=='sky':
                source=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==SKY)
                effects=(Destroy(source,c.source_id),)
            else:
                target=(next(i for i in c.state.players[1].board if c.state.entities[i].card_id==COBALT)if mode=='cobalt'else
                    next(i for i in c.state.players[1].board if c.state.entities[i].card_id==ALL)if mode=='busy'else c.event.target_id)
                effects=(ReturnToHand(target),InvokeBehavior(TEST+'reenter',c.source_id,1,target))
            return(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('change','Change original residency',effects),
                ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_trigger_condition(TEST+'eligible',eligible);r.register_behavior(TEST+'pause',pause)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,
            limited_triggers=(LimitedTriggerSpec(event,TEST+'pause',condition_id=TEST+'eligible'),),metadata=meta()))
    r.validate();return r


@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
    if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable fixture key required')
    r=registry(mode);r.freeze();return r


class SimpleFollowupP72Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),deck=(MECH,)*5,mode=None,seed=7272,enemy_hand=()):
        self.mode=mode
        if mode=='cobalt':board=(WATCH,)+board
        elif mode:enemy=(WATCH,)+enemy
        return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=deck,
            mana=40,max_mana=40,mana_cap=40),PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(BEAST,)*12,mana=40,max_mana=40,mana_cap=40)),seed=seed),
            fixture_registry(mode,'writer',SOURCE_PIN))
    def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def count(self,g,cid,zone='board',pid=1):return sum(g.state.entities[i].card_id==cid for i in getattr(g.state.players[pid],zone))
    def play(self,g,cid,target=None,position=None):
        e=self.first(g,cid);g.apply(PlayCard(1,e.id,target_id=target,position=(len(g.state.players[1].board)if position is None else position)if e.kind==CardType.MINION else None));return e.id
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def next_own(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def portable(self,g):
        reader=fixture_registry(self.mode,'reader',SOURCE_PIN);self.assertIsNot(reader,g.registry)
        self.assertEqual(reader.fingerprint(),g.registry.fingerprint())
        snap=json.loads(json.dumps(g.snapshot()));self.assertEqual(Game.from_snapshot(snap,reader).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap);self.assertEqual(replay(build_replay(g),reader).snapshot(),snap)
        for p in(1,2):
            visible=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('void_cards','rng_state','resolution_frame','source_allocation','behavior_id','original_entities'):
                self.assertNotIn('"'+key+'"',visible)

    def test_a0_real_irida_pays_once_preserves_all_original_void_entities_and_ordinary_draw(self):
        g=self.game((IRIDA,));before=set(g.state.players[1].deck);source=self.play(g,IRIDA)
        p=g.state.players[1];stored={v.entity_id for v in p.void_cards}
        self.assertEqual(len(stored),4);self.assertEqual(stored|set(p.deck),before);self.assertEqual(p.mana,36)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(7,7))
        self.next_own(g);p=g.state.players[1];self.assertEqual(len(p.void_cards),2)
        self.assertEqual(len([d for d in g.state.draw_history if d.player_id==1]),1)
        self.assertEqual(len(stored&set(p.hand)),2);self.assertEqual(len(p.hand),3);self.portable(g)

    def test_a1_irida_player_instance_survives_death_silence_return_transform_and_control(self):
        for tool in(KILL,SILENCE,BOUNCE,CHANGE,STEAL):
            with self.subTest(tool=tool):
                g=self.game((IRIDA,tool));source=self.play(g,IRIDA);self.play(g,tool,source)
                self.next_own(g);self.assertEqual(len(g.state.players[1].void_cards),2)
                self.assertEqual(len(g.state.players[1].player_effects),1);self.assertFalse(g.state.players[2].player_effects);self.portable(g)

    def test_a2_void_wait_restores_failed_choice_and_retired_source_keeps_second_acquisition(self):
        g=self.game((IRIDA,),mode='void');source=self.play(g,IRIDA);self.next_own(g)
        self.assertEqual(len(g.state.players[1].void_cards),3);self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'change')
        self.assertEqual(g.state.entities[source].zone,Zone.SETASIDE);self.assertEqual(len(g.state.players[1].void_cards),2)
        self.assertEqual(len(g.state.players[1].hand),3);self.portable(g)

    def test_a3_void_full_hand_consumes_two_originals_and_native_overflow_then_normal_draw(self):
        g=self.game((IRIDA,FILL));self.play(g,IRIDA);self.play(g,FILL);self.assertEqual(len(g.state.players[1].hand),10)
        self.next_own(g);self.assertEqual(len(g.state.players[1].void_cards),2)
        self.assertEqual(sum(e.kind=='card_burned'and e.player_id==1 for e in g.events),3);self.portable(g)

    def test_a4_empty_and_single_decks_do_not_consume_rng_or_invent_void_members(self):
        for deck in((),(MECH,)):
            g=self.game((IRIDA,),deck=deck);rng=g.snapshot()['rng_state'];self.play(g,IRIDA)
            self.assertFalse(g.state.players[1].void_cards);self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)

    def test_a5_copy_does_not_repeat_battlecry_or_duplicate_the_permanent_player_instance(self):
        g=self.game((IRIDA,COPY));source=self.play(g,IRIDA);self.play(g,COPY,source)
        self.assertEqual(self.count(g,IRIDA),2);self.assertEqual(len(g.state.players[1].player_effects),1)
        self.assertEqual(len(g.state.players[1].void_cards),4);self.portable(g)

    def test_a6_void_original_local_attributes_survive_setaside_and_actual_hand_reacquisition(self):
        g=self.game((DECKBUFF,IRIDA));self.play(g,DECKBUFF);self.play(g,IRIDA);self.next_own(g)
        for i in g.state.players[1].hand:self.assertEqual((g.state.entities[i].attack,g.state.entities[i].health),(3,6))
        self.play(g,MECH);self.assertEqual((self.first(g,MECH,'board').attack,self.first(g,MECH,'board').health),(3,6));self.portable(g)

    def test_a7_two_real_battlecries_append_original_void_members_and_keep_independent_instances(self):
        g=self.game((IRIDA,IRIDA,APPEND));self.play(g,IRIDA);self.play(g,APPEND);self.play(g,IRIDA)
        self.assertEqual(len(g.state.players[1].void_cards),6);self.assertEqual(len(g.state.players[1].player_effects),2)
        self.next_own(g);self.assertEqual(len(g.state.players[1].void_cards),2);self.portable(g)

    def test_b0_glow_tron_native_magnetic_keeps_host_and_silence_removes_material(self):
        g=self.game((GLOW,SILENCE),board=(MECH,));host=self.first(g,MECH,'board').id;source=self.play(g,GLOW,position=0)
        self.assertEqual(g.state.players[1].board,[host]);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual((g.state.entities[host].attack,g.state.entities[host].health),(2,6))
        self.play(g,SILENCE,host);self.assertEqual((g.state.entities[host].attack,g.state.entities[host].health),(1,3));self.portable(g)

    def test_b1_minibot_and_shotbot_have_actual_shield_and_reborn_lifecycles(self):
        g=self.game((MINIBOT,SHOTBOT,HIT,KILL));shield=self.play(g,MINIBOT);self.play(g,HIT,shield)
        self.assertEqual(g.state.entities[shield].health,2);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[shield].keywords)
        source=self.play(g,SHOTBOT);self.play(g,KILL,source);reborn=self.first(g,SHOTBOT,'board')
        self.assertNotEqual(reborn.id,source);self.assertEqual(reborn.health,1);self.assertNotIn(Keyword.REBORN,reborn.keywords);self.portable(g)

    def test_b2_cobalt_ignores_own_entry_and_opponent_but_accepts_current_all_tribe(self):
        g=self.game((COBALT,ALL,HIT),enemy_hand=(MINIBOT,));source=self.play(g,COBALT);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords)
        self.play(g,ALL);self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords);self.play(g,HIT,source)
        g.apply(EndTurn(1));enemy=self.first(g,MINIBOT,pid=2);g.apply(PlayCard(2,enemy.id,position=len(g.state.players[2].board)))
        self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords);self.portable(g)

    def test_b3_cobalt_old_queued_grant_cannot_shield_same_id_reentry(self):
        g=self.game((MINIBOT,),board=(COBALT,),mode='cobalt');source=self.first(g,COBALT,'board').id;self.play(g,MINIBOT)
        self.portable(g);self.choose(g,'change');self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords);self.portable(g)

    def test_c0_bubble_other_mech_all_and_original_residency_survive_wait_rollback(self):
        g=self.game((BUBBLE,),board=(MECH,ALL,BEAST),mode='bubble');original=self.first(g,MECH,'board').id
        self.play(g,BUBBLE);self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'change')
        self.assertNotIn(Keyword.TAUNT,g.state.entities[original].keywords);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[original].keywords)
        for k in(Keyword.TAUNT,Keyword.DIVINE_SHIELD):self.assertIn(k,self.first(g,ALL,'board').keywords)
        self.assertFalse(self.first(g,BEAST,'board').keywords);self.assertFalse(self.first(g,BUBBLE,'board').keywords);self.portable(g)

    def test_c1_busy_uses_current_attack_and_does_not_rebind_later_old_recipient(self):
        g=self.game((BUSY,),board=(MECH,ALL,BEAST),mode='busy');original=self.first(g,ALL,'board').id;self.play(g,BUSY)
        self.portable(g);self.choose(g,'change');self.assertEqual(g.state.entities[original].attack,1)
        self.assertEqual(self.first(g,MECH,'board').attack,2);self.assertEqual(self.first(g,BEAST,'board').attack,2);self.portable(g)

    def test_d0_egg_original_death_slot_and_attributed_quantity_two_robosaurs(self):
        g=self.game((KILL,),board=(DOUBLE,EGG,BEAST));source=self.first(g,EGG,'board').id;self.play(g,KILL,source)
        self.assertEqual(self.count(g,ROBOSAUR),2);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[DOUBLE,ROBOSAUR,ROBOSAUR,BEAST])
        self.assertTrue(all(r.request.cause.source.entity_id==source for r in g.state.card_summon_history));self.portable(g)

    def test_d1_sky_two_actual_copters_quantity_and_current_other_mech_aura(self):
        g=self.game((SKY,SILENCE),board=(DOUBLE,ALL));source=self.play(g,SKY)
        self.assertEqual(self.count(g,COPTER),4);self.assertEqual(self.first(g,ALL,'board').attack,2)
        self.assertEqual(self.first(g,DOUBLE,'board').attack,0);self.assertEqual(g.state.entities[source].attack,1)
        self.play(g,SILENCE,source);self.assertEqual(self.first(g,ALL,'board').attack,1)
        self.assertTrue(all(g.state.entities[i].attack==1 for i in g.state.players[1].board if g.state.entities[i].card_id==COPTER));self.portable(g)

    def test_d2_sky_first_body_wait_rollback_and_source_retirement_keep_second_request(self):
        g=self.game((SKY,),mode='sky');source=self.play(g,SKY);self.assertEqual(self.count(g,COPTER),1);self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'change')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.count(g,COPTER),2);self.portable(g)

    def test_d3_sky_actual_one_free_slot_skips_second_copter_without_fake_capacity(self):
        g=self.game((SKY,),board=(BEAST,)*5);self.play(g,SKY)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(self.count(g,COPTER),1);self.portable(g)

    def test_e0_mummy_owner_end_empty_pool_and_reborn_keep_existing_native_rules(self):
        g=self.game(board=(MUMMY,));rng=g.snapshot()['rng_state'];g.apply(EndTurn(1));self.assertEqual(g.snapshot()['rng_state'],rng)
        g=self.game((KILL,),board=(MUMMY,MECH));source=self.first(g,MUMMY,'board').id;self.play(g,KILL,source)
        self.assertEqual(self.first(g,MUMMY,'board').health,1);self.assertNotEqual(self.first(g,MUMMY,'board').id,source)
        g.apply(EndTurn(1));self.assertEqual(self.first(g,MECH,'board').attack,2);g.apply(EndTurn(2))
        self.assertEqual(self.first(g,MECH,'board').attack,2);self.portable(g)

    def test_z0_complete_sources_count_actual_new_ids_and_preserve_central_assembly(self):
        from tools.card_batch import check_face
        d=load_batch();self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['official_observations'])),(1,11,34))
        rows={x['record']['id']:x['record']for k in('cards','dependencies','evidence_only')for x in d[k]}
        for o in d['official_observations']:check_face(rows[o['card_id']],o['face'],o['locale'],{},numeric_normalizations=d['numeric_normalizations'].get(o['card_id']))
        before,after=build_registry(),batch_registry()
        for cid,c in before.cards.items():self.assertEqual(after.card(cid),c)
        for cid,c in before.pool_cards.items():self.assertEqual(after.pool_card(cid),c)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS)-set(before.cards));self.assertTrue(set(ROOTS)<=set(after.cards))
        self.assertEqual(set(after.player_effects)-set(before.player_effects),{VOID}-set(before.player_effects))
        for key in('player_effects','fabled','jade_families','generation_families','pools'):
            for cid,value in getattr(before,key).items():self.assertEqual(getattr(after,key)[cid],value)
        for cid in d['unsupported_source_cards']:self.assertEqual(cid in before.cards,cid in after.cards)


if __name__=='__main__':unittest.main()
