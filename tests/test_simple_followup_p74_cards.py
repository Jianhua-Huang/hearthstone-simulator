"""Original conditional grants and real independent Colossal family lifecycles."""
from functools import lru_cache
import hashlib,json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p74_cards as cards
from hs_sim.cards.simple_followup_p74_cards import (GOLDWING,HYDRALODON,HEAD,RIGHT_HEAD,CLAW,
    WEAPON,RIGHT_CLAW,SHELL,HAND,RIGHT_HAND,ROOTS,PREFIX,load_batch,register_simple_followup_p74_cards)
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,
    IllegalAction,Keyword,PlayerSetup,PlayCard,Rarity,Registry,Scenario,SelectChoice,TargetSpec,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Damage,DamageBatch,Destroy,
    InvokeBehavior,RequestChoice,ReturnToHand,Silence,TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference,LimitedTriggerSpec,SummonQuantitySpec,TribeChangeSpec
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonEntryMaterial
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference

TEST='p74.test.'
HERO,HP,MECH,ALL,BEAST,DOUBLE,WATCH=(TEST+i for i in('hero','power','mech','all','beast','double','watch'))
KILL,BOUNCE,SILENCE,STEAL,COPY,WIPE,TRIBE,SUMMON,TRIGGER=(TEST+i for i in
    ('kill','bounce','silence','steal','copy','wipe','tribe','summon','trigger'))
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()


def meta(tribes=(),collectible=True,cls=CardClass.NEUTRAL):
    return CardMetadata(collectible,(cls,),Rarity.COMMON if collectible else None,tribes=tribes)


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    present=tuple(cid in r.cards for cid in ROOTS)
    if not any(present):register_simple_followup_p74_cards(r)
    elif not all(present):raise AssertionError('P74 requires its complete assigned assembly')
    register_candidate_pool_metadata(r);r.validate();return r


def registry(mode=None):
    r=Registry('p74-small-native-fixtures');register_simple_followup_p74_cards(r)
    r.register_behavior(TEST+'nop',lambda c:())
    r.register_card(CardDefinition(HP,HP,CardType.HERO_POWER,cost=2,on_use=TEST+'nop',metadata=meta(collectible=False,cls=CardClass.PALADIN)))
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,initial_hero_power=HP,metadata=meta(collectible=False,cls=CardClass.PALADIN)))
    for cid,atk,hp,tribes in((MECH,1,3,('mech',)),(ALL,1,4,('all',)),(BEAST,2,30,('beast',))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=atk,health=hp,metadata=meta(tribes)))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=30,summon_quantities=(SummonQuantitySpec(2),),metadata=meta()))
    def fail(c):raise ResolutionError('P74 deliberate continuation failure')
    def reenter(c):return(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),1),)
    r.register_behavior(TEST+'fail',fail);r.register_behavior(TEST+'reenter',reenter)
    bodies={KILL:lambda c:(Destroy(c.target_id,c.source_id),),BOUNCE:lambda c:(ReturnToHand(c.target_id),),
        SILENCE:lambda c:(Silence(c.target_id),),STEAL:lambda c:(ChangeControl(c.target_id,2),),
        COPY:lambda c:(CopyMinion(BoardPresenceReference.capture(c.state,c.target_id),1,cause=cards.SummonCause.capture(c)),),
        WIPE:lambda c:(DamageBatch(tuple(Damage(i,999,c.source_id)for p in c.state.players.values()for i in p.board)),),
        TRIBE:lambda c:(ChangeMinionTribes(CardReference.capture(c.state.entities[next(i for i in c.state.players[1].hand if c.state.entities[i].card_id==BEAST)]),TribeChangeSpec('set',('mech',)),c.source_id),),
        SUMMON:lambda c:(SummonByCard(1,(SummonEntryMaterial(HYDRALODON),),cards.SummonCause.capture(c)),),
        TRIGGER:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            targeting=TargetSpec()if cid in(KILL,BOUNCE,SILENCE,STEAL,COPY,TRIGGER)else None,metadata=meta()))
    if mode:
        event='minion_summoned'if mode=='heads'else'battlecry_started'if mode=='goldwing'else'ability_granted'
        def eligible(c):
            if mode=='goldwing':return c.state.entities[c.event.source_id].card_id==GOLDWING
            target=c.state.entities.get(c.event.target_id)
            return target is not None and target.controller==1 and target.card_id==HEAD and (
                mode=='heads'or dict(c.event.data).get('ability_kind')=='keyword')
        def watcher(c):
            if mode=='heads':
                double=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==DOUBLE)
                parent=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==HYDRALODON)
                changed=(RemoveFromGame((MinionReference.capture(c.state.entities[double]),),c.source_id),)
                killed=(Destroy(parent,c.source_id),)
            else:
                target=c.event.source_id if mode=='goldwing'else next(i for i in c.state.players[1].board if c.state.entities[i].card_id==RIGHT_HEAD)
                changed=(ReturnToHand(target),InvokeBehavior(TEST+'reenter',c.source_id,1,target));killed=()
            return(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('change','Change original residency',changed),
                ChoiceOption('kill','Retire parent',killed),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_trigger_condition(TEST+'eligible',eligible);r.register_behavior(TEST+'pause',watcher)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,
            limited_triggers=(LimitedTriggerSpec(event,TEST+'pause',condition_id=TEST+'eligible'),),metadata=meta()))
    r.validate();return r


@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
    if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable fixture key required')
    r=registry(mode);r.freeze();return r


class SimpleFollowupP74Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),mode=None,enemy_hand=()):
        self.mode=mode
        if mode:enemy=(WATCH,)+enemy
        return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=(BEAST,)*12,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(BEAST,)*12,mana=50,max_mana=50,mana_cap=50)),seed=7474),fixture_registry(mode,'writer',SOURCE_PIN))
    def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def count(self,g,cid,zone='board',pid=1):return sum(g.state.entities[i].card_id==cid for i in getattr(g.state.players[pid],zone))
    def play(self,g,cid,target=None,position=None):
        e=self.first(g,cid);g.apply(PlayCard(1,e.id,target_id=target,position=(len(g.state.players[1].board)if position is None else position)if e.kind==CardType.MINION else None));return e.id
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        reader=fixture_registry(self.mode,'reader',SOURCE_PIN);self.assertIsNot(reader,g.registry)
        self.assertEqual(reader.fingerprint(),g.registry.fingerprint());snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,reader).snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),snap)
        for p in(1,2):
            visible=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','source_allocation','behavior_id','original_entities'):self.assertNotIn('"'+key+'"',visible)
    def rollback(self,g):
        self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)

    def test_a0_goldwing_dual_printed_tribe_and_actual_other_hand_mech_or_all_grant_windfury(self):
        for held in(MECH,ALL):
            g=self.game((GOLDWING,held));source=self.play(g,GOLDWING);e=g.state.entities[source]
            self.assertEqual(g.registry.card(GOLDWING).metadata.tribes,('dragon','mech'))
            self.assertTrue({Keyword.RUSH,Keyword.WINDFURY}<=set(e.keywords));self.assertEqual(g.state.players[1].mana,46);self.portable(g)

    def test_a1_goldwing_does_not_count_itself_opponent_hand_or_non_mech(self):
        for hand in((GOLDWING,),(GOLDWING,BEAST)):
            g=self.game(hand,enemy_hand=(MECH,));source=self.play(g,GOLDWING)
            self.assertNotIn(Keyword.WINDFURY,g.state.entities[source].keywords);self.assertIn(Keyword.RUSH,g.state.entities[source].keywords);self.portable(g)

    def test_a2_goldwing_uses_current_hand_tribe_and_native_windfury_attack_limit(self):
        g=self.game((TRIBE,GOLDWING,BEAST),enemy=(BEAST,));self.play(g,TRIBE);source=self.play(g,GOLDWING)
        self.assertIn(Keyword.WINDFURY,g.state.entities[source].keywords);target=self.first(g,BEAST,'board',2).id
        with self.assertRaises(IllegalAction):g.apply(Attack(1,source,g.state.players[2].hero_id))
        g.apply(Attack(1,source,target));g.apply(Attack(1,source,target))
        with self.assertRaises(IllegalAction):g.apply(Attack(1,source,target))
        self.assertEqual(g.state.entities[source].health,1);self.assertEqual(len(g.state.character_attack_history),2);self.portable(g)

    def test_a3_goldwing_wait_and_failed_choice_do_not_grant_to_new_same_id_source(self):
        g=self.game((GOLDWING,MECH),mode='goldwing');source=self.play(g,GOLDWING);self.rollback(g);self.choose(g,'change')
        self.assertIn(source,g.state.players[1].board);self.assertNotIn(Keyword.WINDFURY,g.state.entities[source].keywords)
        self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_b0_paid_hydralodon_gives_all_current_heads_rush_but_not_itself(self):
        g=self.game((HYDRALODON,),board=(HEAD,RIGHT_HEAD));source=self.play(g,HYDRALODON)
        self.assertEqual(g.state.players[1].mana,43);self.assertEqual(len(g.state.colossal_history),1)
        self.assertEqual((self.count(g,HEAD),self.count(g,RIGHT_HEAD)),(2,2))
        for i in g.state.players[1].board:
            if i!=source:self.assertIn(Keyword.RUSH,g.state.entities[i].keywords)
        self.assertNotIn(Keyword.RUSH,g.state.entities[source].keywords);self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_b1_attributed_summon_and_quantity_do_not_invent_hydralodon_battlecry(self):
        g=self.game((SUMMON,),board=(DOUBLE,));source=self.play(g,SUMMON)
        self.assertEqual((self.count(g,HYDRALODON),self.count(g,HEAD),self.count(g,RIGHT_HEAD)),(2,2,2))
        self.assertFalse(g.state.battlecry_history);self.assertEqual(len(g.state.colossal_history),2)
        self.assertEqual(g.state.card_summon_history[0].request.cause.source.entity_id,source)
        self.assertTrue(all(Keyword.RUSH not in g.state.entities[i].keywords for i in g.state.players[1].board));self.portable(g)

    def test_b2_hydralodon_partial_colossal_capacity_keeps_only_real_delivered_head(self):
        g=self.game((HYDRALODON,),board=(BEAST,)*5);self.play(g,HYDRALODON)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(self.count(g,HEAD)+self.count(g,RIGHT_HEAD),1)
        self.assertIn(Keyword.RUSH,self.first(g,HEAD,'board').keywords);self.portable(g)

    def test_b3_pending_hydralodon_grant_skips_later_same_id_head_reentry(self):
        g=self.game((HYDRALODON,),board=(HEAD,RIGHT_HEAD),mode='hydra');original=self.first(g,RIGHT_HEAD,'board').id
        self.play(g,HYDRALODON);self.rollback(g);self.choose(g,'change')
        self.assertIn(original,g.state.players[1].board);self.assertNotIn(Keyword.RUSH,g.state.entities[original].keywords)
        self.assertEqual(sum(Keyword.RUSH in g.state.entities[i].keywords for i in g.state.players[1].board),3);self.portable(g)

    def test_c0_both_head_faces_natural_death_spawn_exact_two_named_heads_at_original_slot(self):
        for cid in(HEAD,RIGHT_HEAD):
            g=self.game((KILL,),board=(HYDRALODON,MECH,cid,BEAST));source=self.first(g,cid,'board').id;self.play(g,KILL,source)
            self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[HYDRALODON,MECH,HEAD,HEAD,BEAST])
            self.assertEqual(len(g.state.card_summon_history),2)
            self.assertTrue(all(r.request.cause.source.entity_id==source for r in g.state.card_summon_history))
            self.assertTrue(all(Keyword.RUSH not in g.state.entities[i].keywords for i in g.state.players[1].board if g.state.entities[i].card_id==HEAD));self.portable(g)

    def test_c1_head_without_own_living_parent_and_simultaneous_parent_death_do_not_summon(self):
        g=self.game((KILL,),board=(HEAD,),enemy=(HYDRALODON,));self.play(g,KILL,self.first(g,HEAD,'board').id)
        self.assertFalse(g.state.card_summon_history);self.portable(g)
        g=self.game((WIPE,),board=(HYDRALODON,HEAD,RIGHT_HEAD));self.play(g,WIPE)
        self.assertFalse(g.state.players[1].board);self.assertFalse(g.state.card_summon_history);self.portable(g)

    def test_c2_heads_native_quantity_and_partial_capacity_use_real_member_results(self):
        for board,expected in(((HYDRALODON,DOUBLE,HEAD),4),((HYDRALODON,HEAD)+(BEAST,)*5,1)):
            g=self.game((KILL,),board=board);self.play(g,KILL,self.first(g,HEAD,'board').id)
            self.assertEqual(self.count(g,HEAD),expected);self.assertEqual(len(g.state.card_summon_history),2);self.portable(g)

    def test_c3_first_accepted_head_quantity_survives_wait_later_member_recomputes(self):
        g=self.game((KILL,),board=(HYDRALODON,DOUBLE,HEAD),mode='heads');self.play(g,KILL,self.first(g,HEAD,'board').id)
        self.assertEqual(self.count(g,HEAD),1);self.rollback(g);self.choose(g,'change')
        self.assertEqual(self.count(g,HEAD),3);self.assertEqual(self.count(g,DOUBLE),0);self.portable(g)

    def test_c4_accepted_two_head_requests_survive_later_parent_death(self):
        g=self.game((KILL,),board=(HYDRALODON,DOUBLE,HEAD),mode='heads');self.play(g,KILL,self.first(g,HEAD,'board').id)
        self.rollback(g);self.choose(g,'kill');self.assertEqual(self.count(g,HYDRALODON),0)
        self.assertEqual(self.count(g,HEAD),4);self.portable(g)

    def test_c5_head_death_uses_its_actual_death_controller_and_live_manual_activation_position(self):
        g=self.game((STEAL,KILL),board=(HEAD,),enemy=(HYDRALODON,));source=self.first(g,HEAD,'board').id
        self.play(g,STEAL,source);self.play(g,KILL,source)
        self.assertEqual(self.count(g,HEAD,pid=2),2);self.assertEqual(self.count(g,HEAD),0);self.portable(g)
        g=self.game((TRIGGER,),board=(HYDRALODON,RIGHT_HEAD,MECH));source=self.first(g,RIGHT_HEAD,'board').id;self.play(g,TRIGGER,source)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[HYDRALODON,RIGHT_HEAD,HEAD,HEAD,MECH])
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.portable(g)

    def test_c6_real_rushing_head_combat_death_creates_new_heads_without_rush(self):
        g=self.game((HYDRALODON,),enemy=(BEAST,));self.play(g,HYDRALODON);source=self.first(g,HEAD,'board').id
        g.apply(Attack(1,source,self.first(g,BEAST,'board',2).id));self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(self.count(g,HEAD),2);self.assertTrue(all(Keyword.RUSH not in g.state.entities[i].keywords for i in g.state.players[1].board if g.state.entities[i].card_id==HEAD));self.portable(g)

    def test_d0_both_claws_rush_attack_die_and_equip_exact_two_one_weapon(self):
        for cid in(CLAW,RIGHT_CLAW):
            g=self.game((cid,),enemy=(BEAST,));source=self.play(g,cid);g.apply(Attack(1,source,self.first(g,BEAST,'board',2).id))
            weapon=g.state.entities[g.state.players[1].weapon_id];self.assertEqual((weapon.card_id,weapon.attack,weapon.durability),(WEAPON,2,1))
            self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
            g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id));self.assertIsNone(g.state.players[1].weapon_id)
            self.assertEqual(g.state.entities[weapon.id].zone,Zone.GRAVEYARD);self.portable(g)

    def test_d1_actual_claw_death_replaces_old_weapon_and_ordinary_silence_removes_deathrattle(self):
        g=self.game((WEAPON,KILL),board=(CLAW,));old=self.play(g,WEAPON);self.play(g,KILL,self.first(g,CLAW,'board').id)
        self.assertNotEqual(g.state.players[1].weapon_id,old);self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.portable(g)
        g=self.game((SILENCE,KILL),board=(RIGHT_CLAW,));source=self.first(g,RIGHT_CLAW,'board').id
        self.play(g,SILENCE,source);self.play(g,KILL,source);self.assertIsNone(g.state.players[1].weapon_id);self.portable(g)

    def test_e0_shell_zero_attack_taunt_and_copied_actual_deaths_gain_eight_armor_each(self):
        g=self.game((SHELL,COPY,KILL,KILL));source=self.play(g,SHELL);self.assertEqual(g.state.entities[source].attack,0)
        self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords);self.play(g,COPY,source)
        self.play(g,KILL,source);self.play(g,KILL,self.first(g,SHELL,'board').id)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,16);self.assertFalse(g.state.players[1].board);self.portable(g)

    def test_e1_shell_death_armor_belongs_to_actual_controller(self):
        g=self.game((STEAL,KILL),board=(SHELL,));source=self.first(g,SHELL,'board').id;self.play(g,STEAL,source);self.play(g,KILL,source)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,8);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.portable(g)

    def test_f0_both_hands_are_immune_only_during_own_attack_and_have_one_attack(self):
        for cid in(HAND,RIGHT_HAND):
            g=self.game(board=(cid,),enemy=(BEAST,));source=self.first(g,cid,'board').id;target=self.first(g,BEAST,'board',2).id
            g.apply(Attack(1,source,target));self.assertEqual(g.state.entities[source].health,2)
            with self.assertRaises(IllegalAction):g.apply(Attack(1,source,target))
            g.apply(EndTurn(1));g.apply(Attack(2,target,source));self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.portable(g)

    def test_f1_played_hands_have_no_parent_rush_and_silence_removes_attack_immunity(self):
        g=self.game((HAND,),enemy=(BEAST,));source=self.play(g,HAND)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,source,self.first(g,BEAST,'board',2).id))
        self.portable(g)
        g=self.game((SILENCE,),board=(RIGHT_HAND,),enemy=(BEAST,));source=self.first(g,RIGHT_HAND,'board').id;self.play(g,SILENCE,source)
        g.apply(Attack(1,source,self.first(g,BEAST,'board',2).id));self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.portable(g)

    def test_z0_full_sources_actual_new_ids_and_old_assembled_content_are_preserved(self):
        from tools.card_batch import check_face
        d=load_batch();self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['official_observations']),len(d['rejected_complete_primary_observations'])),(0,10,40,8))
        rows={x['record']['id']:x['record']for k in('dependencies','evidence_only')for x in d[k]}
        for o in d['official_observations']:check_face(rows[o['card_id']],o['face'],o['locale'],{},numeric_normalizations=d['numeric_normalizations'].get(o['card_id']))
        for o in d['rejected_complete_primary_observations']:
            with self.assertRaises(ValueError):check_face(rows[o['card_id']],o['face'],o['locale'],{})
        before,after=build_registry(),batch_registry()
        for cid,c in before.cards.items():self.assertEqual(after.card(cid),c)
        for cid,c in before.pool_cards.items():self.assertEqual(after.pool_card(cid),c)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS)-set(before.cards));self.assertTrue(set(ROOTS)<=set(after.cards))
        for key in('player_effects','fabled','jade_families','generation_families','pools'):self.assertEqual(getattr(before,key),getattr(after,key))
        for cid in d['unsupported_source_cards']:self.assertEqual(cid in before.cards,cid in after.cards)


if __name__=='__main__':unittest.main()
