"""Complete real Shatter families and post-draw/post-death second components."""
from dataclasses import asdict,replace
import json,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p20_cards import SUPPLY,FLOW,SUPPLY_DRAW,SUPPLY_BUFF,FLOW_HIT,FLOW_AOE,ROOTS,DEPENDENCIES,PYROMANCER,load_batch,register_simple_followup_p20_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,CostSpec,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SpellSchool,TargetSpec,Zone
from hs_sim.engine.effects import AddToHand,ChoiceOption,Damage,Draw,InvokeBehavior,ModifyCost,RequestChoice,ReturnToHand,Summon
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import CardReference,CopyCard
from hs_sim.targets import canonical_digest
TEST='p20.test.';YETI='CORE_CS2_182';SPELL='CORE_CS2_029';META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def registry(mode=None):
    r=build_registry();ids=ROOTS+DEPENDENCIES
    if not all(cid in r.cards for cid in ids):register_simple_followup_p20_cards(r)
    def copy(c,mode):
        source=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id in ROOTS)
        return(CopyCard(CardReference.capture(source),c.player_id,mode=mode,source_id=c.source_id),)
    for name,body in(('generate_supply',lambda c:(AddToHand(1,SUPPLY,c.source_id),)),('generate_flow',lambda c:(AddToHand(1,FLOW,c.source_id),)),
        ('enemy_generate',lambda c:(AddToHand(2,FLOW,c.source_id),)),('generate_full',lambda c:(AddToHand(1,YETI,c.source_id),AddToHand(1,FLOW,c.source_id))),('damage',lambda c:(Damage(c.target_id,26,c.source_id),)),
        ('copy_current',lambda c:copy(c,'current')),('copy_base',lambda c:copy(c,'base'))):
        key=TEST+name;r.register_behavior(key,body);r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META,requires_target=name=='damage'))
    r.register_behavior(TEST+'token',lambda c:(Summon(c.player_id,TEST+'token'),))
    r.register_card(CardDefinition(TEST+'token','Deathrattle body',CardType.MINION,health=3,metadata=META))
    r.register_card(CardDefinition(TEST+'spawn','First-hit death witness',CardType.MINION,health=4,deathrattle=TEST+'token',metadata=META))
    r.register_card(CardDefinition(TEST+'power','Original first-hit spell bonus',CardType.MINION,health=3,spell_damage=2,metadata=META))
    r.register_card(CardDefinition(TEST+'large','Large target',CardType.MINION,health=20,metadata=META))
    r.register_card(CardDefinition(TEST+'dormant','Dormant target',CardType.MINION,health=8,dormant_turns=2,metadata=META))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P20 deliberate pending failure')))
    def wait(c):return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(Summon(c.player_id,TEST+'token'),)),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(TEST+'wait_death',wait);r.register_card(CardDefinition(TEST+'wait_spawn','Pending death witness',CardType.MINION,health=4,deathrattle=TEST+'wait_death',metadata=META))
    if mode:
        def eligible(c):return c.event.player_id==1
        def watch(c):
            target=c.event.target_id;extra=(AddToHand(1,TEST+'large',c.source_id),)if mode=='draw_add'else()
            if mode=='draw_remove':extra=(Summon(1,YETI),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',extra),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'own_draw',eligible)
        r.register_card(CardDefinition(TEST+'watch','First real draw reaction',CardType.MINION,health=9,metadata=META,
            limited_triggers=(LimitedTriggerSpec('card_drawn',TEST+'watch',condition_id=TEST+'own_draw'),)))
    r.validate();return r

class SimpleFollowupP20Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),deck=(YETI,)*5,board=(),enemy=(),enemy_hand=(),mode=None):
        self.mode=mode;r=registry(mode)if mode else self.r
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,board=board,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*5,mana=50,max_mana=50,mana_cap=50)),seed=2020),r)
    def first(self,g,cid,p=1,zone='hand'):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def hand(self,g,p=1):return[g.state.entities[i]for i in g.state.players[p].hand]
    def names(self,g,p=1):return[e.card_id for e in self.hand(g,p)]
    def hero(self,g,p=2):return g.state.entities[g.state.players[p].hero_id]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.mode));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','CardReference','fragment_ids','behavior_id'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_complete_eight_raw_rows_twelve_faces_school_and_child_identity(self):
        d=load_batch();self.assertEqual(len(d['cards']+d['dependencies']+d['existing_dependencies']+d['evidence_only']),8);self.assertEqual(len(d['official_observations']['observations']),12);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_@]','',s)
        for row in d['cards']+d['dependencies']:
            raw=row['record'];cid=raw['id'];self.assertEqual(canonical_digest(raw),row['record_sha256']);card=self.r.card(cid);self.assertEqual(card.metadata,replace(metadata_from_record(raw),deck_identity=cid));self.assertEqual(card.cost,4);self.assertEqual(card.metadata.collectible,cid in ROOTS)
            self.assertEqual(card.spell_school,SpellSchool.ARCANE if cid in(FLOW,FLOW_HIT,FLOW_AOE)else None)
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale'].lower().replace('_','-')=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost'],f['cardSetId']),(raw['dbf_id'],4,raw['card_set_id']))
                if cid in ROOTS:self.assertEqual(f['childIds'],[121758,121760]if cid==SUPPLY else[123743,123744])
        self.assertEqual(self.r.card(SUPPLY).shatter.left_card_id,SUPPLY_DRAW);self.assertEqual(self.r.card(FLOW).shatter.right_card_id,FLOW_AOE);self.assertIsNone(self.r.card(FLOW_AOE).targeting);self.assertIsNotNone(self.r.card(FLOW_HIT).targeting)
        for cid in DEPENDENCIES:self.assertEqual(self.r.card(cid).keywords,(Keyword.SHATTERED,))

    def test_only_complete_six_definitions_added_old_definitions_and_evidence_preserved(self):
        with patch('hs_sim.cards.simple_followup_p20_cards.register_simple_followup_p20_cards',lambda r:None):before=build_registry()
        after=build_registry()
        if not all(cid in after.cards for cid in ROOTS+DEPENDENCIES):register_simple_followup_p20_cards(after)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS+DEPENDENCIES));self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual('CATA_820e'in before.cards,'CATA_820e'in after.cards)

    def test_default311_and_full_fingerprint_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')

    def test_both_real_roots_split_to_exact_opposite_fragments(self):
        for root,left,right in((SUPPLY,SUPPLY_DRAW,SUPPLY_BUFF),(FLOW,FLOW_HIT,FLOW_AOE)):
            with self.subTest(root=root):
                g=self.game((root,YETI));self.assertEqual(self.names(g),[left,YETI,right]);self.assertEqual(len([e for e in g.events if e.kind=='card_shattered']),1);self.assertFalse(g.state.play_history);self.assertFalse(g.state.death_history)

    def test_adjacent_real_fragments_recombine_consumed_shatter_and_whole_pays_once(self):
        g=self.game((FLOW_HIT,FLOW_AOE));self.assertEqual(self.names(g),[FLOW]);self.assertNotIn(Keyword.SHATTER,self.first(g,FLOW).keywords);self.play(g,FLOW,self.hero(g).id);self.assertEqual(self.hero(g).health,24);self.assertEqual(g.state.players[1].mana,46);self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_supply_whole_draws_three_once_and_buffs_old_and_new_hand_minions_once(self):
        g=self.game((SUPPLY_DRAW,SUPPLY_BUFF,YETI),deck=(YETI,YETI,SPELL,YETI,SPELL));source=self.play(g,SUPPLY);minions=[e for e in self.hand(g)if e.kind==CardType.MINION];self.assertEqual(len(minions),4);self.assertTrue(all((e.attack,e.max_health)==(6,7)for e in minions));self.assertEqual(len(g.state.players[1].deck),2);self.assertEqual(g.state.players[1].mana,46);self.assertEqual(len([e for e in g.events if e.kind=='card_drawn']),3);self.assertTrue(all(e.source_id==source for e in g.events if e.kind=='card_drawn'));self.portable(g)

    def test_supply_draw_fragment_has_no_buff_and_only_minion_tutor(self):
        g=self.game((SUPPLY_DRAW,),deck=(SPELL,YETI,SPELL,YETI,YETI));self.play(g,SUPPLY_DRAW);self.assertEqual(len(self.hand(g)),3);self.assertTrue(all((e.card_id,e.attack,e.max_health)==(YETI,4,5)for e in self.hand(g)));self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[SPELL,SPELL])

    def test_supply_buff_fragment_affects_only_current_friendly_hand_minions(self):
        g=self.game((SUPPLY_BUFF,YETI,SPELL),board=(YETI,),enemy=(YETI,),enemy_hand=(YETI,));self.play(g,SUPPLY_BUFF);self.assertEqual((self.first(g,YETI).attack,self.first(g,YETI).max_health),(6,7));self.assertEqual(self.first(g,YETI,1,'board').attack,4);self.assertEqual(self.first(g,YETI,1,'deck').attack,4);self.assertEqual(self.first(g,YETI,2).attack,4);self.assertEqual(self.first(g,YETI,2,'board').attack,4);self.assertFalse([e for e in g.events if e.kind=='card_drawn'])

    def test_supply_empty_and_no_minion_decks_skip_without_fatigue_or_rng(self):
        for deck in((),(SPELL,SPELL)):
            with self.subTest(deck=deck):
                g=self.game((SUPPLY_DRAW,),deck=deck);rng=g.snapshot()['rng_state'];self.play(g,SUPPLY_DRAW);self.assertEqual(self.hero(g,1).health,30);self.assertFalse(self.hand(g));self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_supply_full_hand_draws_burn_real_minions_before_remaining_hand_buff(self):
        g=self.game((SUPPLY_DRAW,SUPPLY_BUFF)+(YETI,)*8,deck=(YETI,)*3);self.assertEqual(len(self.hand(g)),9);self.play(g,SUPPLY);self.assertEqual(len(self.hand(g)),10);self.assertFalse(g.state.players[1].deck);self.assertTrue(all((e.attack,e.max_health)==(6,7)for e in self.hand(g)));self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),1)

    def test_supply_draw_wait_observes_new_reaction_added_hand_minion_before_buff(self):
        g=self.game((SUPPLY_DRAW,SUPPLY_BUFF),deck=(YETI,)*3,board=(TEST+'watch',),mode='draw_add');self.play(g,SUPPLY);self.assertIsNotNone(g.state.pending_choice);self.assertTrue(all(e.attack==4 for e in self.hand(g)if e.card_id==YETI));other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len([e for e in self.hand(g)if e.card_id==YETI]),3);self.assertTrue(all(e.attack==6 for e in self.hand(g)if e.card_id==YETI));self.assertEqual((self.first(g,TEST+'large').attack,self.first(g,TEST+'large').max_health),(2,22));self.portable(g)

    def test_flow_targeted_fragment_deals_four_only_and_whole_target_rules_rollback(self):
        g=self.game((FLOW_HIT,));self.play(g,FLOW_HIT,self.hero(g).id);self.assertEqual(self.hero(g).health,26)
        for card in(FLOW,FLOW_HIT):
            for kind in('none','dormant','hand'):
                with self.subTest(card=card,kind=kind):
                    hand=(FLOW_HIT,FLOW_AOE,YETI)if card==FLOW else(FLOW_HIT,YETI);g=self.game(hand,enemy=(TEST+'dormant',));target=None if kind=='none'else self.first(g,TEST+'dormant',2,'board').id if kind=='dormant'else self.first(g,YETI).id;saved=g.snapshot()
                    with self.assertRaises(IllegalAction):self.play(g,card,target)
                    self.assertEqual(g.snapshot(),saved)

    def test_flow_aoe_fragment_has_no_target_hits_enemy_hero_and_minions_only(self):
        g=self.game((FLOW_AOE,),board=(YETI,),enemy=(YETI,TEST+'dormant'));self.play(g,FLOW_AOE);self.assertEqual(self.hero(g).health,28);self.assertEqual(self.first(g,YETI,2,'board').health,3);self.assertEqual(self.first(g,YETI,1,'board').health,5);self.assertEqual(self.first(g,TEST+'dormant',2,'board').health,8)

    def test_flow_whole_has_four_then_two_distinct_batches_and_single_cast(self):
        g=self.game((FLOW_HIT,FLOW_AOE),enemy=(TEST+'large',YETI));target=self.first(g,TEST+'large',2,'board').id;source=self.play(g,FLOW,target);self.assertEqual(g.state.entities[target].health,14);self.assertEqual(self.first(g,YETI,2,'board').health,3);self.assertEqual(self.hero(g).health,28)
        rows=[health_result(e)for e in g.events if e.kind=='health_resolved'and health_result(e).source_id==source];self.assertEqual([r.base_amount for r in rows],[4,2,2,2]);self.assertEqual(len({r.batch_id for r in rows}),2);self.assertTrue(all(r.damage_kind=='spell'for r in rows));self.assertEqual(len(g.state.cast_history),1)

    def test_flow_second_aoe_includes_new_deathrattle_body_after_first_hit(self):
        g=self.game((FLOW_HIT,FLOW_AOE),enemy=(TEST+'spawn',));target=self.first(g,TEST+'spawn',2,'board').id;self.play(g,FLOW,target);self.assertEqual(self.first(g,TEST+'token',2,'board').health,1);self.assertEqual(len(g.state.death_history),1);self.assertEqual(self.hero(g).health,28);self.portable(g)

    def test_flow_spell_damage_applies_to_both_halves_and_current_bonus_recomputed(self):
        g=self.game((FLOW_HIT,FLOW_AOE),board=(TEST+'power',),enemy=(TEST+'large',));self.play(g,FLOW,self.hero(g).id);self.assertEqual(self.hero(g).health,20);self.assertEqual(self.first(g,TEST+'large',2,'board').health,16)
        g=self.game((FLOW_HIT,FLOW_AOE),board=(TEST+'power',),enemy=(TEST+'large',));target=self.first(g,TEST+'power',1,'board').id;self.play(g,FLOW,target);self.assertEqual(self.hero(g).health,28);self.assertEqual(self.first(g,TEST+'large',2,'board').health,18)

    def test_flow_first_hit_lethal_hero_stops_second_payload(self):
        g=self.game((TEST+'damage',FLOW_HIT,FLOW_AOE),enemy=(YETI,));self.play(g,TEST+'damage',self.hero(g).id);self.play(g,FLOW,self.hero(g).id);self.assertEqual(self.first(g,YETI,2,'board').health,5);self.assertEqual(g.state.status,'finished')

    def test_flow_waiting_first_death_restore_replay_failure_then_fresh_aoe(self):
        g=self.game((FLOW_HIT,FLOW_AOE),enemy=(TEST+'wait_spawn',));self.play(g,FLOW,self.first(g,TEST+'wait_spawn',2,'board').id);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.hero(g).health,30);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.first(g,TEST+'token',2,'board').health,1);self.assertEqual(self.hero(g).health,28);self.assertEqual(g.state.players[1].mana,46);self.portable(g)

    def test_native_current_copy_of_combined_real_root_preserves_consumed_shatter(self):
        g=self.game((FLOW_HIT,FLOW_AOE,TEST+'copy_current'));self.play(g,TEST+'copy_current');self.assertEqual(self.names(g),[FLOW,FLOW]);self.assertTrue(all(Keyword.SHATTER not in e.keywords for e in self.hand(g)));self.portable(g)

    def test_native_base_copy_of_combined_real_root_reinstalls_split(self):
        g=self.game((FLOW_HIT,FLOW_AOE,TEST+'copy_base'));self.play(g,TEST+'copy_base');self.assertEqual(self.names(g),[FLOW_HIT,FLOW,FLOW_AOE]);self.assertEqual(len([e for e in g.events if e.kind=='card_shattered']),1);self.portable(g)

    def test_real_supply_and_flow_entry_trigger_existing_pyromancer_once_each(self):
        for root,script,left,right in((SUPPLY,TEST+'generate_supply',SUPPLY_DRAW,SUPPLY_BUFF),(FLOW,TEST+'generate_flow',FLOW_HIT,FLOW_AOE)):
            with self.subTest(root=root):
                g=self.game((script,YETI),board=(PYROMANCER,),enemy=(TEST+'large',));self.play(g,script);self.assertEqual(self.first(g,TEST+'large',2,'board').health,18);self.assertEqual(self.names(g),[left,YETI,right]);self.assertEqual(len([e for e in g.events if e.kind=='card_shattered']),1);self.assertEqual(self.hero(g).health,30)

    def test_actual_enemy_shatter_uses_enemy_pyromancer_and_not_own_same_name(self):
        g=self.game((TEST+'enemy_generate',YETI),board=(PYROMANCER,YETI),enemy=(PYROMANCER,YETI));self.play(g,TEST+'enemy_generate');self.assertEqual(self.first(g,YETI,1,'board').health,3);self.assertEqual(self.first(g,YETI,2,'board').health,5);self.assertEqual(self.first(g,PYROMANCER,1,'board').health,1);self.assertEqual(self.first(g,PYROMANCER,2,'board').health,3)

    def test_real_shatter_one_free_hand_slot_burns_only_right_fragment_and_triggers_once(self):
        g=self.game((TEST+'generate_flow',)+(YETI,)*9,board=(PYROMANCER,),enemy=(YETI,));# playing source frees exactly one slot: one fragment survives, the other burns
        self.play(g,TEST+'generate_flow');self.assertEqual(len(self.hand(g)),10);self.assertIn(FLOW_HIT,self.names(g));self.assertNotIn(FLOW_AOE,self.names(g));self.assertEqual(self.first(g,YETI,2,'board').health,3);self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),1)

    def test_real_shatter_root_burn_in_full_hand_does_not_split_or_trigger(self):
        g=self.game((TEST+'generate_full',)+(YETI,)*9,board=(PYROMANCER,),enemy=(YETI,));self.play(g,TEST+'generate_full');self.assertEqual(len(self.hand(g)),10);self.assertFalse([e for e in g.events if e.kind=='card_shattered']);self.assertEqual(self.first(g,YETI,2,'board').health,5);self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),1)

if __name__=='__main__':unittest.main()
