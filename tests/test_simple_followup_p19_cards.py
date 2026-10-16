"""Real trigger consumers: native Shatter events, immutable healing and forced combat."""
from dataclasses import asdict,replace
import json,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p19_cards import PYROMANCER,SHADOW,ROOTS,DEPENDENCIES,load_batch,register_simple_followup_p19_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,TargetSpec,Zone
from hs_sim.engine.effects import AddToHand,ChangeControl,ChoiceOption,Damage,DamageBatch,Destroy,Freeze,GrantHealthRule,Heal,HealBatch,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import DamageKind,HealthFlow,HealthOp,HealthRule,LimitedTriggerSpec,TriggerSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.targets import canonical_digest
from test_m5_shatter import family
TEST='p19.test.';YETI='CORE_CS2_182';META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def registry(mode=None):
    r=build_registry()
    if not all(cid in r.cards for cid in ROOTS):register_simple_followup_p19_cards(r)
    # Reuse the baseline's complete executable three-face Shatter fixture;
    # this is native hand settlement, never a forged card_shattered event.
    family(r,TEST+'split',metadata=META)
    def from_healer(c,p):
        source=next(i for i in c.state.players[p].board if c.state.entities[i].card_id==TEST+'healer')
        return(Heal(c.target_id,2,source),)
    bodies={
        'damage':lambda c:(Damage(c.target_id,2,c.source_id),),'hurt':lambda c:(Damage(c.target_id,10,c.source_id),),
        'heal':lambda c:(Heal(c.target_id,2,c.source_id),),'zero':lambda c:(Heal(c.target_id,0,c.source_id),),
        'double_heal':lambda c:(Heal(c.target_id,1,c.source_id),Heal(c.target_id,1,c.source_id)),
        'own_heal':lambda c:from_healer(c,1),'enemy_heal':lambda c:from_healer(c,2),
        'silence':lambda c:(Silence(c.target_id),),'give':lambda c:(ChangeControl(c.target_id,2),),'take':lambda c:(ChangeControl(c.target_id,1),),
        'freeze':lambda c:(Freeze(c.target_id),),'bounce':lambda c:(ReturnToHand(c.target_id,to_owner=True),),
        'convert':lambda c:(GrantHealthRule(c.target_id,HealthRule(HealthFlow.HEALING,HealthOp.CONVERT,source_relation='friendly'),c.source_id),),
        'generate':lambda c:(AddToHand(c.player_id,TEST+'split',c.source_id),),
        'enemy_generate':lambda c:(AddToHand(2,TEST+'split',c.source_id),),
    }
    for name,body in bodies.items():
        key=TEST+name;r.register_behavior(key,body);target=None if name.endswith('generate')else TargetSpec()
        r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,targeting=target,metadata=META))
    r.register_card(CardDefinition(TEST+'large','Large combat target',CardType.MINION,attack=1,health=30,metadata=META))
    r.register_card(CardDefinition(TEST+'small','Simultaneous death target',CardType.MINION,health=2,metadata=META))
    r.register_card(CardDefinition(TEST+'healer','Physical healing source',CardType.MINION,health=8,metadata=META))
    r.register_card(CardDefinition(TEST+'dormant','Dormant excluded',CardType.MINION,health=9,dormant_turns=2,metadata=META))
    r.register_card(CardDefinition(TEST+'spellpower','Spell bonus excluded',CardType.MINION,health=3,spell_damage=8,metadata=META))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P19 deliberate pending failure')))
    if mode:
        def condition(c):
            if mode.startswith('shatter'):return c.event.kind=='card_shattered'and c.event.player_id==1
            result=c.health_result
            return result is not None and result.flow=='healing'and result.healed>0 and result.source_controller==1 and result.target_controller==2
        def watch(c):
            result=c.health_result;effects=()
            if mode=='heal_control':
                return(ChangeControl(result.source_id,2),)
            if mode=='heal_target_control':return(ChangeControl(result.target_id,1),)
            if mode in('heal_source_return','heal_target_return'):
                target=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==SHADOW)if mode=='heal_source_return'else result.target_id
                pid=c.state.entities[target].controller
                effects=(ReturnToHand(target,to_owner=True),SummonFromZone(pid,zone=Zone.HAND,selection='first',source_id=c.source_id,cause=SummonCause.capture(c)))
            if mode=='shatter_fail':return(InvokeBehavior(TEST+'fail',c.source_id,c.player_id),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',effects),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'watch_condition',condition)
        r.register_card(CardDefinition(TEST+'watch','Original event boundary',CardType.MINION,health=9,metadata=META,
            limited_triggers=(LimitedTriggerSpec('card_shattered'if mode.startswith('shatter')else'health_resolved',TEST+'watch',condition_id=TEST+'watch_condition'),)))
    r.validate();return r

class SimpleFollowupP19Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),mode=None):
        self.mode=mode;r=registry(mode)if mode else self.r
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50)),seed=1919),r)
    def first(self,g,cid,p=1,zone='board'):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid,1,'hand').id;g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def attacks(self,g):return[e for e in g.events if e.kind=='attack_declared'and g.state.entities[e.source_id].card_id==SHADOW]
    def results(self,g):return[health_result(e)for e in g.events if e.kind=='health_resolved']
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.mode));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','HealthResult','source_controller','board_presence_id','fragment_ids'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_complete_raw_faces_and_exact_metadata(self):
        d=load_batch();self.assertEqual(len(d['cards']),2);self.assertEqual(len(d['official_observations']['observations']),4);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(self.r.card(raw['id']).metadata,replace(metadata_from_record(raw),deck_identity=raw['id']))
            for o in(o for o in d['official_observations']['observations']if o['card_id']==raw['id']):
                f=o['face'];en=o['locale'].lower().replace('_','-')=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost'],f['attack'],f['health'],f['cardSetId']),(raw['dbf_id'],raw['cost'],raw['attack'],raw['health'],raw['card_set_id']))
        self.assertEqual(self.r.card(PYROMANCER).metadata.tribes,());self.assertEqual(self.r.card(SHADOW).metadata.tribes,('elemental',));self.assertEqual(self.r.card(SHADOW).keywords,(Keyword.LIFESTEAL,));self.assertIsNone(self.r.card(SHADOW).battlecry)

    def test_only_two_roots_added_and_all_old_definitions_unchanged(self):
        with patch('hs_sim.cards.simple_followup_p19_cards.register_simple_followup_p19_cards',lambda r:None):before=build_registry()
        after=build_registry()
        if not all(cid in after.cards for cid in ROOTS):register_simple_followup_p19_cards(after)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertFalse(DEPENDENCIES);self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards))

    def test_default_311_definitions_and_fingerprint_remain(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')

    def test_pyromancer_paid_native_face_then_actual_shatter_hits_all_enemies(self):
        g=self.game((PYROMANCER,TEST+'generate'),enemy=(YETI,YETI));source=self.play(g,PYROMANCER);self.play(g,TEST+'generate');self.assertEqual(g.state.players[1].mana,47);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(4,3));self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[3,3]);self.assertEqual(self.hero(g,2).health,30)
        event,=[e for e in g.events if e.kind=='card_shattered'];self.assertEqual(event.player_id,1);self.assertEqual(len(dict(event.data)['fragment_ids']),2);hits=[r for r in self.results(g)if r.source_id==source];self.assertEqual(len(hits),2);self.assertEqual({r.damage_kind for r in hits},{DamageKind.MINION_ABILITY.value});self.assertEqual(len({r.batch_id for r in hits}),1);self.portable(g)

    def test_pyromancer_ignores_enemy_shatter_and_enemy_same_name_listener(self):
        g=self.game((TEST+'enemy_generate',TEST+'generate'),(PYROMANCER,),(PYROMANCER,YETI));self.play(g,TEST+'enemy_generate');self.assertEqual(self.first(g,PYROMANCER).health,1);self.assertEqual(self.first(g,YETI,2).health,5);self.play(g,TEST+'generate');self.assertEqual(self.first(g,PYROMANCER,2).health,1);self.assertEqual(self.first(g,YETI,2).health,3)

    def test_pyromancer_only_enemy_minions_excludes_dormant_and_spell_damage(self):
        g=self.game((TEST+'generate',),(PYROMANCER,TEST+'spellpower',YETI),(YETI,TEST+'dormant'));self.play(g,TEST+'generate');self.assertEqual(self.first(g,YETI,2).health,3);self.assertEqual(self.first(g,TEST+'dormant',2).health,9);self.assertEqual(self.first(g,YETI).health,5);self.assertEqual(self.first(g,PYROMANCER).health,3)

    def test_pyromancer_two_carriers_each_get_independent_native_shatter_window(self):
        g=self.game((TEST+'generate',),(PYROMANCER,PYROMANCER),(YETI,));self.play(g,TEST+'generate');self.assertEqual(self.first(g,YETI,2).health,1);self.assertEqual(len([r for r in self.results(g)if r.damage_kind==DamageKind.MINION_ABILITY.value]),2)

    def test_pyromancer_simultaneous_lethals_have_same_damage_batch(self):
        g=self.game((TEST+'generate',),(PYROMANCER,),(TEST+'small',TEST+'small'));self.play(g,TEST+'generate');self.assertFalse(g.state.players[2].board);self.assertEqual(len(g.state.death_history),2);self.assertEqual(len({r.batch_id for r in self.results(g)}),1)

    def test_pyromancer_silence_prevents_future_shatter_and_control_uses_new_owner(self):
        g=self.game((TEST+'silence',TEST+'generate'),(PYROMANCER,),(YETI,));self.play(g,TEST+'silence',self.first(g,PYROMANCER).id);self.play(g,TEST+'generate');self.assertEqual(self.first(g,YETI,2).health,5)
        g=self.game((TEST+'give',TEST+'generate',TEST+'enemy_generate'),(PYROMANCER,YETI),(YETI,));eid=self.first(g,PYROMANCER).id;self.play(g,TEST+'give',eid);self.play(g,TEST+'generate');self.assertEqual(self.first(g,YETI,2).health,5);self.play(g,TEST+'enemy_generate');self.assertEqual(self.first(g,YETI).health,3)

    def test_pyromancer_bounce_and_paid_reentry_restore_printed_listener(self):
        g=self.game((TEST+'silence',TEST+'bounce',TEST+'generate'),(PYROMANCER,),(YETI,));eid=self.first(g,PYROMANCER).id;self.play(g,TEST+'silence',eid);self.play(g,TEST+'bounce',eid);self.play(g,PYROMANCER);self.play(g,TEST+'generate');self.assertEqual(self.first(g,YETI,2).health,3)

    def test_pyromancer_native_shatter_failure_rolls_back_generation_fragments_damage_rng(self):
        g=self.game((TEST+'generate',),(TEST+'watch',PYROMANCER),(YETI,),mode='shatter_fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,TEST+'generate')
        self.assertEqual(g.snapshot(),saved)

    def test_pyromancer_native_shatter_waiting_restore_and_bad_choice_atomic(self):
        g=self.game((TEST+'generate',),(TEST+'watch',PYROMANCER),(YETI,),mode='shatter_wait');self.play(g,TEST+'generate');self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.first(g,YETI,2).health,3);self.portable(g)

    def test_shadow_paid_fresh_minion_forces_real_combat_and_lifesteal(self):
        g=self.game((SHADOW,TEST+'damage',TEST+'hurt',TEST+'heal'),enemy=(TEST+'large',));source=self.play(g,SHADOW);target=self.first(g,TEST+'large',2).id;self.play(g,TEST+'damage',target);self.play(g,TEST+'hurt',g.state.players[1].hero_id);self.play(g,TEST+'heal',target)
        self.assertEqual(g.state.players[1].mana,43);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(6,6));self.assertEqual(g.state.entities[target].health,24);self.assertEqual(self.hero(g).health,26);event,=self.attacks(g);self.assertTrue(dict(event.data)['forced']);self.assertEqual(event.target_id,target);self.portable(g)

    def test_shadow_heals_enemy_hero_despite_recipient_event_player_id(self):
        g=self.game((TEST+'damage',TEST+'heal'),(SHADOW,));target=g.state.players[2].hero_id;self.play(g,TEST+'damage',target);self.play(g,TEST+'heal',target);self.assertEqual(self.hero(g,2).health,24);self.assertEqual(len(self.attacks(g)),1)
        heal=[e for e in g.events if e.kind=='health_resolved'and health_result(e).healed>0][0];self.assertEqual((heal.player_id,health_result(heal).source_controller,health_result(heal).target_controller),(2,1,2))

    def test_shadow_enemy_owned_healing_source_does_not_count_as_you(self):
        g=self.game((TEST+'damage',TEST+'enemy_heal'),(SHADOW,),(TEST+'healer',TEST+'large'));target=self.first(g,TEST+'large',2).id;self.play(g,TEST+'damage',target);self.play(g,TEST+'enemy_heal',target);self.assertFalse(self.attacks(g));self.assertEqual(g.state.entities[target].health,30)

    def test_shadow_friendly_heal_full_health_and_zero_actual_heal_do_not_attack(self):
        for target_kind in('friendly','full_enemy','zero'):
            with self.subTest(target_kind=target_kind):
                g=self.game((TEST+'damage',TEST+'heal',TEST+'zero'),(SHADOW,YETI),(TEST+'large',));target=self.first(g,YETI).id if target_kind=='friendly'else self.first(g,TEST+'large',2).id
                if target_kind!='full_enemy':self.play(g,TEST+'damage',target)
                self.play(g,TEST+'zero'if target_kind=='zero'else TEST+'heal',target);self.assertFalse(self.attacks(g))

    def test_shadow_healing_converted_to_damage_does_not_attack(self):
        g=self.game((TEST+'convert',TEST+'heal'),(SHADOW,),(TEST+'large',));target=self.first(g,TEST+'large',2).id;self.play(g,TEST+'convert',self.first(g,SHADOW).id);self.play(g,TEST+'heal',target);self.assertFalse(self.attacks(g));result=self.results(g)[-1];self.assertEqual((result.original_flow,result.flow,result.healed),('healing','damage',0))

    def test_shadow_two_actual_heals_produce_two_forced_attacks_without_readiness_limit(self):
        g=self.game((TEST+'damage',TEST+'double_heal'),(SHADOW,),(TEST+'large',));target=self.first(g,TEST+'large',2).id;self.play(g,TEST+'damage',target);self.play(g,TEST+'double_heal',target);self.assertEqual(len(self.attacks(g)),2);self.assertEqual(g.state.entities[target].health,18);self.assertEqual(self.first(g,SHADOW).health,5)

    def test_shadow_frozen_source_still_uses_existing_forced_attack_policy(self):
        g=self.game((TEST+'freeze',TEST+'damage',TEST+'heal'),(SHADOW,),(TEST+'large',));self.play(g,TEST+'freeze',self.first(g,SHADOW).id);target=self.first(g,TEST+'large',2).id;self.play(g,TEST+'damage',target);self.play(g,TEST+'heal',target);self.assertEqual(len(self.attacks(g)),1);self.assertTrue(self.first(g,SHADOW).frozen)

    def test_shadow_silence_removes_listener_and_lifesteal(self):
        g=self.game((TEST+'silence',TEST+'damage',TEST+'heal'),(SHADOW,),(TEST+'large',));self.play(g,TEST+'silence',self.first(g,SHADOW).id);target=self.first(g,TEST+'large',2).id;self.play(g,TEST+'damage',target);self.play(g,TEST+'heal',target);self.assertFalse(self.attacks(g));self.assertNotIn(Keyword.LIFESTEAL,self.first(g,SHADOW).keywords)

    def test_shadow_source_controller_is_frozen_before_later_control_change(self):
        g=self.game((TEST+'damage',TEST+'own_heal'),(TEST+'watch',TEST+'healer',SHADOW),(TEST+'large',),mode='heal_control');target=self.first(g,TEST+'large',2).id;source=self.first(g,TEST+'healer').id;self.play(g,TEST+'damage',target);self.play(g,TEST+'own_heal',target);self.assertEqual(g.state.entities[source].controller,2);self.assertEqual(len(self.attacks(g)),1);self.assertEqual(self.results(g)[1].source_controller,1)

    def test_shadow_original_enemy_healed_then_control_transfer_prevents_friendly_combat(self):
        g=self.game((TEST+'damage',TEST+'heal'),(TEST+'watch',SHADOW),(TEST+'large',),mode='heal_target_control');target=self.first(g,TEST+'large',2).id;self.play(g,TEST+'damage',target);self.play(g,TEST+'heal',target);self.assertEqual(g.state.entities[target].controller,1);self.assertFalse(self.attacks(g))

    def test_shadow_waiting_heal_source_or_target_return_reentry_cannot_rebind(self):
        for mode in('heal_source_return','heal_target_return'):
            with self.subTest(mode=mode):
                g=self.game((TEST+'damage',TEST+'heal'),(TEST+'watch',SHADOW),(TEST+'large',),mode=mode);target=self.first(g,TEST+'large',2).id;self.play(g,TEST+'damage',target);self.play(g,TEST+'heal',target);other=self.portable(g);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.choose(g,'bad')
                self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertFalse(self.attacks(g));self.portable(g)

    def test_shadow_current_controller_qualifies_healing_after_borrowing(self):
        g=self.game((TEST+'take',TEST+'damage',TEST+'heal'),(),(SHADOW,TEST+'large'));source=self.first(g,SHADOW,2).id;self.play(g,TEST+'take',source);target=self.first(g,TEST+'large',2).id;self.play(g,TEST+'damage',target);self.play(g,TEST+'heal',target);self.assertEqual(len(self.attacks(g)),1);self.assertEqual(g.state.entities[source].owner,2)

if __name__=='__main__':unittest.main()
