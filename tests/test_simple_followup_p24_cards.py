"""Raincaller's native per-global-turn budget over settled spell damage."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import asdict,replace
import json,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p24_cards import RAIN,FIREBALL,ROOTS,DEPENDENCIES,PREFIX,load_batch,register_simple_followup_p24_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.effects import ChangeControl,ChoiceOption,CopyMinion,Damage,DamageBatch,GainArmor,Heal,InvokeBehavior,RequestChoice,ReturnToHand,Silence
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import DamageKind,HealthFlow,HealthOp,HealthRule,LimitedTriggerSpec
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.targets import canonical_digest
from tools.card_batch import registration_prefix
TEST='p24.test.';YETI='CORE_CS2_182';META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def registry(mode=None):
    r=build_registry()
    if RAIN not in r.cards:register_simple_followup_p24_cards(r)
    def minion_hit(c):
        source=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==TEST+'dealer')
        return(Damage(c.target_id,1,source,DamageKind.MINION_ABILITY),)
    bodies={'zero':lambda c:(Damage(c.target_id,0,c.source_id,DamageKind.SPELL),),'effect':lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.EFFECT),),
        'heal':lambda c:(Heal(c.target_id,2,c.source_id),),'minion_hit':minion_hit,
        'batch':lambda c:(DamageBatch(tuple(Damage(i,1,c.source_id,DamageKind.SPELL)for i in c.state.players[2].board)),),
        'armor':lambda c:(GainArmor(2,10),),'enemy_cast':lambda c:(CastSpell(2,FIREBALL,c.source_id,c.state.players[1].hero_id,targeting='explicit'),),
        'silence':lambda c:(Silence(c.target_id),),'bounce':lambda c:(ReturnToHand(c.target_id,to_owner=True),),
        'copy':lambda c:(CopyMinion(c.target_id,1),),'base_copy':lambda c:(CopyMinion(c.target_id,1,mode='base'),),
        'steal':lambda c:(ChangeControl(c.target_id,2),)}
    for name,body in bodies.items():
        key=TEST+name;r.register_behavior(key,body);r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META,requires_target=name not in('batch','armor','enemy_cast')))
    r.register_card(CardDefinition(TEST+'large','Large positive health target',CardType.MINION,health=40,metadata=META))
    r.register_card(CardDefinition(TEST+'shield','Prevented first packet',CardType.MINION,health=8,keywords=(Keyword.DIVINE_SHIELD,),metadata=META))
    r.register_card(CardDefinition(TEST+'dealer','Non-spell ability source',CardType.MINION,health=8,metadata=META))
    r.register_card(CardDefinition(TEST+'convert','Final healing flow provider',CardType.MINION,health=8,metadata=META,
        health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.CONVERT,source_relation='friendly'),)))
    r.register_behavior(TEST+'opponent_turn',lambda c:(CastSpell(1,FIREBALL,c.source_id,c.state.players[2].hero_id,targeting='explicit'),)if c.event.player_id==2 else())
    r.register_card(CardDefinition(TEST+'opponent_turn','Owner spell on opponent actual turn',CardType.MINION,health=8,metadata=META,triggers=(TriggerSpec('turn_started',TEST+'opponent_turn'),)))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P24 deliberate pending failure')))
    if mode:
        def eligible(c):
            if mode=='wait':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==RAIN
            result=c.health_result
            return result is not None and result.flow=='damage'and result.damage_dealt>0 and result.damage_kind=='spell'and result.source_controller==1
        def watch(c):
            extra=()
            if mode=='return':
                target=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==RAIN)
                extra=(ReturnToHand(target,to_owner=True),SummonFromZone(1,zone=Zone.HAND,selection='first',query=PoolQuery(kinds=(CardType.MINION,)),source_id=c.source_id,cause=SummonCause.capture(c)))
            return(RequestChoice(1,(ChoiceOption('ok','Continue',extra),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','Actual finite window observer',CardType.MINION,health=8,metadata=META,
            limited_triggers=(LimitedTriggerSpec('limited_trigger_used'if mode=='wait'else'health_resolved',TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

class SimpleFollowupP24Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),mode=None):
        self.mode=mode;r=registry(mode)if mode else self.r
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50)),seed=2424),r)
    def first(self,g,cid,p=1,zone='board'):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid,zone='hand').id;g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def budget(self,g,eid):return next(a for a in g.state.entities[eid].abilities if a.kind=='limited_trigger'and a.limited_trigger.behavior_id==PREFIX+'gain')
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.mode));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','trigger_turn','HealthResult','source_controller','behavior_id'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_two_complete_raw_rows_two_official_faces_exact_mage_elemental_and_budget(self):
        d=load_batch();self.assertEqual(len(d['cards']+d['existing_dependencies']),2);self.assertEqual(len(d['official_observations']['observations']),2);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete']);raw=d['cards'][0]['record'];self.assertEqual(canonical_digest(raw),d['cards'][0]['record_sha256'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for o in d['official_observations']['observations']:
            f=o['face'];en=o['locale'].lower().replace('_','-')=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost'],f['attack'],f['health'],f['minionTypeId']),(123419,2,1,4,18))
        card=self.r.card(RAIN);self.assertEqual(card.metadata,replace(metadata_from_record(raw),deck_identity=RAIN));self.assertEqual(card.metadata.classes,(CardClass.MAGE,));self.assertEqual(card.metadata.tribes,('elemental',));self.assertFalse(card.keywords);self.assertIsNone(card.battlecry);self.assertEqual((card.limited_triggers[0].uses,card.limited_triggers[0].reset),(1,'turn'));self.assertEqual(raw['tags']['4548'],1)

    def test_only_one_definition_added_and_complete_old_definitions_unchanged(self):
        before=registration_prefix(build_registry,'hs_sim.cards.simple_followup_p24_cards.register_simple_followup_p24_cards',register_simple_followup_p24_cards)
        after=registration_prefix(build_registry,'hs_sim.cards.simple_followup_p24_cards.register_simple_followup_p24_cards',register_simple_followup_p24_cards,after=True)
        if RAIN not in after.cards:register_simple_followup_p24_cards(after)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertFalse(DEPENDENCIES);self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards))

    def test_default311_complete_fingerprint_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_paid_native_rain_and_real_fireball_give_exact_plus_two_attack_once(self):
        g=self.game((RAIN,FIREBALL,FIREBALL),enemy=(TEST+'large',));source=self.play(g,RAIN);target=self.first(g,TEST+'large',2).id;self.play(g,FIREBALL,target);self.play(g,FIREBALL,target);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health,g.state.entities[source].max_health),(3,4,4));self.assertEqual(g.state.players[1].mana,40);self.assertEqual(self.budget(g,source).uses_remaining,0);self.portable(g)

    def test_multiple_spell_packets_in_same_batch_spend_budget_once(self):
        g=self.game((TEST+'batch',),(RAIN,),(TEST+'large',TEST+'large'));source=self.first(g,RAIN).id;self.play(g,TEST+'batch');self.assertEqual(g.state.entities[source].attack,3);self.assertEqual(len([e for e in g.events if e.kind=='limited_trigger_used'and e.source_id==source]),1)

    def test_two_carriers_have_independent_physical_budgets(self):
        g=self.game((FIREBALL,FIREBALL),(RAIN,RAIN),(TEST+'large',));target=self.first(g,TEST+'large',2).id;self.play(g,FIREBALL,target);self.play(g,FIREBALL,target);cards=[g.state.entities[i]for i in g.state.players[1].board];self.assertTrue(all(e.attack==3 for e in cards));self.assertEqual(len({self.budget(g,e.id).id for e in cards}),2)

    def test_next_global_opponent_turn_refreshes_and_own_automatic_spell_can_trigger(self):
        g=self.game((FIREBALL,FIREBALL),(RAIN,TEST+'opponent_turn'));source=self.first(g,RAIN).id;self.play(g,FIREBALL,g.state.players[2].hero_id);self.assertEqual(g.state.entities[source].attack,3);g.apply(EndTurn(1));self.assertEqual(g.state.active_player,2);self.assertEqual(g.state.entities[source].attack,5);self.assertEqual(self.budget(g,source).uses_remaining,0);g.apply(EndTurn(2));self.play(g,FIREBALL,g.state.players[2].hero_id);self.assertEqual(g.state.entities[source].attack,7);self.portable(g)

    def test_original_spell_controller_not_health_event_recipient_decides_you(self):
        g=self.game((TEST+'enemy_cast',FIREBALL),(RAIN,));source=self.first(g,RAIN).id;self.play(g,TEST+'enemy_cast');self.assertEqual(g.state.entities[source].attack,1);self.assertEqual(self.budget(g,source).uses_remaining,1);enemy_result=next(health_result(e)for e in g.events if e.kind=='health_resolved');self.assertEqual((enemy_result.source_controller,enemy_result.target_controller),(2,1));self.play(g,FIREBALL,g.state.players[2].hero_id);self.assertEqual(g.state.entities[source].attack,3)

    def test_actual_damage_to_armor_counts_even_without_health_loss(self):
        g=self.game((TEST+'armor',FIREBALL),(RAIN,));source=self.first(g,RAIN).id;self.play(g,TEST+'armor');self.play(g,FIREBALL,g.state.players[2].hero_id);self.assertEqual(g.state.entities[source].attack,3);result=next(health_result(e)for e in g.events if e.kind=='health_resolved');self.assertEqual((result.damage_dealt,result.armor_absorbed,result.health_lost),(6,6,0))

    def test_zero_prevented_and_healing_results_do_not_consume_first_positive_spell(self):
        g=self.game((TEST+'zero',TEST+'heal',FIREBALL,FIREBALL),(RAIN,),(TEST+'shield',TEST+'large'));source=self.first(g,RAIN).id;target=self.first(g,TEST+'large',2).id;self.play(g,TEST+'zero',target);self.play(g,TEST+'heal',target);self.play(g,FIREBALL,self.first(g,TEST+'shield',2).id);self.assertEqual((g.state.entities[source].attack,self.budget(g,source).uses_remaining),(1,1));self.play(g,FIREBALL,target);self.assertEqual(g.state.entities[source].attack,3)

    def test_nonspell_effect_and_minion_ability_do_not_consume_budget(self):
        g=self.game((TEST+'effect',TEST+'minion_hit',FIREBALL),(RAIN,TEST+'dealer'),(TEST+'large',));source=self.first(g,RAIN).id;target=self.first(g,TEST+'large',2).id;self.play(g,TEST+'effect',target);self.play(g,TEST+'minion_hit',target);self.assertEqual((g.state.entities[source].attack,self.budget(g,source).uses_remaining),(1,1));self.play(g,FIREBALL,target);self.assertEqual(g.state.entities[source].attack,3)

    def test_spell_damage_converted_to_healing_is_not_positive_damage(self):
        g=self.game((FIREBALL,),(RAIN,TEST+'convert'),(TEST+'large',));source=self.first(g,RAIN).id;self.play(g,FIREBALL,self.first(g,TEST+'large',2).id);self.assertEqual((g.state.entities[source].attack,self.budget(g,source).uses_remaining),(1,1));result=next(health_result(e)for e in g.events if e.kind=='health_resolved');self.assertEqual((result.original_flow,result.flow,result.damage_dealt),('damage','healing',0))

    def test_silence_removes_trigger_and_accumulated_attack_without_turn_reinstall(self):
        g=self.game((FIREBALL,TEST+'silence',FIREBALL),(RAIN,),(TEST+'large',));source=self.first(g,RAIN).id;target=self.first(g,TEST+'large',2).id;self.play(g,FIREBALL,target);self.play(g,TEST+'silence',source);g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,FIREBALL,target);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(1,4));self.assertFalse([a for a in g.state.entities[source].abilities if a.kind=='limited_trigger'])

    def test_return_and_paid_reentry_reset_printed_stats_and_physical_budget(self):
        g=self.game((FIREBALL,TEST+'bounce',FIREBALL),(RAIN,),(TEST+'large',));source=self.first(g,RAIN).id;target=self.first(g,TEST+'large',2).id;self.play(g,FIREBALL,target);old=self.budget(g,source).id;self.play(g,TEST+'bounce',source);self.play(g,RAIN);self.assertEqual(g.state.entities[source].attack,1);self.assertNotEqual(self.budget(g,source).id,old);self.play(g,FIREBALL,target);self.assertEqual(g.state.entities[source].attack,3)

    def test_current_copy_preserves_consumed_budget_base_copy_has_new_budget(self):
        g=self.game((FIREBALL,TEST+'copy',TEST+'base_copy',FIREBALL),(RAIN,),(TEST+'large',));source=self.first(g,RAIN).id;target=self.first(g,TEST+'large',2).id;self.play(g,FIREBALL,target);self.play(g,TEST+'copy',source);self.play(g,TEST+'base_copy',source);cards=[g.state.entities[i]for i in g.state.players[1].board];self.assertEqual([e.attack for e in cards],[3,3,1]);self.assertEqual([self.budget(g,e.id).uses_remaining for e in cards],[0,0,1]);self.play(g,FIREBALL,target);self.assertTrue(all(g.state.entities[e.id].attack==3 for e in cards));self.portable(g)

    def test_control_transfer_keeps_spent_budget_on_same_global_turn(self):
        g=self.game((FIREBALL,TEST+'steal',TEST+'enemy_cast'),(RAIN,));source=self.first(g,RAIN).id;self.play(g,FIREBALL,g.state.players[2].hero_id);self.play(g,TEST+'steal',source);self.play(g,TEST+'enemy_cast');self.assertEqual((g.state.entities[source].controller,g.state.entities[source].attack,self.budget(g,source).uses_remaining),(2,3,0))

    def test_consumed_budget_wait_restores_once_and_failed_resume_rolls_back(self):
        g=self.game((FIREBALL,),(TEST+'watch',RAIN),(TEST+'large',),mode='wait');source=self.first(g,RAIN).id;self.play(g,FIREBALL,self.first(g,TEST+'large',2).id);self.assertIsNotNone(g.state.pending_choice);self.assertEqual((g.state.entities[source].attack,self.budget(g,source).uses_remaining),(1,0));other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual((g.state.entities[source].attack,self.budget(g,source).uses_remaining),(3,0));self.portable(g)

    def test_queued_old_source_does_not_rebind_after_same_id_return_reentry(self):
        g=self.game((FIREBALL,FIREBALL),(TEST+'watch',RAIN),(TEST+'large',),mode='return');source=self.first(g,RAIN).id;old=g.state.entities[source].entered_order;target=self.first(g,TEST+'large',2).id;self.play(g,FIREBALL,target);self.choose(g);self.assertNotEqual(g.state.entities[source].entered_order,old);self.assertEqual((g.state.entities[source].attack,self.budget(g,source).uses_remaining),(1,1));self.play(g,FIREBALL,target);self.assertEqual(g.state.entities[source].attack,3)

if __name__=='__main__':unittest.main()
