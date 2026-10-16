"""Actual source cards, distinct damage and captured stored copies at real waits."""
from dataclasses import replace
import json,unittest
from tests import test_reactive_growth_cards as fixtures
from hs_sim.cards.trigger_source_cards import load_batch
from hs_sim.engine import(CardClass,CardDefinition,CardMetadata,CardType,Game,PlayCard,PlayerSetup,Scenario,
    SelectChoice,SnapshotError,TriggerSpec,Zone,Attack,EndTurn)
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.effects import(AddToHand,Buff,ChoiceOption,Damage,Draw,InvokeBehavior,RandomDamageBatch,RequestChoice,Silence)
from hs_sim.engine.cross_zone import BuffStoredCard
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import CostSpec,DamageKind,Keyword
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard
from hs_sim.targets import canonical_digest

CHO='CORE_EX1_100';COLD='CORE_RLK_083';KEY='CORE_SCH_717';BOL='CORE_SW_047';EREDAR='CORE_TTN_843';MOON='EDR_254'
BAT='TTN_843t1';YETI='CORE_CS2_182';SHIELD='CORE_EX1_008';INTELLECT='CORE_CS2_023';FIRE='CORE_CS2_029'
ROOTS=(CHO,COLD,KEY,BOL,EREDAR,MOON)


def registry(mode=None):
    r=fixtures.registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
    def first(c,p,zone):return c.state.entities[getattr(c.state.players[p],zone)[0]]
    def prep(c):
        return(BuffStoredCard(CardReference.capture(first(c,2,'deck')),2,3,c.source_id,cost=CostSpec(delta=-1)),)
    def capture(c):
        material=CapturedCardCopyMaterial.capture(c.state,first(c,1,'deck'))
        effect=CopyCard(material,1,source_id=c.source_id,cost=CostSpec(set_to=1))
        return(RequestChoice(1,(ChoiceOption('ok','Copy',(effect,)),
            ChoiceOption('bad','Failure',(InvokeBehavior('k28.fail',c.source_id,c.player_id),))),c.source_id),)
    def discount(c):
        from hs_sim.engine.zones import ModifyStoredCost
        source=next(c.state.entities[i]for i in c.state.players[1].hand if c.state.entities[i].card_id==FIRE)
        return(ModifyStoredCost(CardReference.capture(source),CostSpec(delta=-2),c.source_id),)
    def batch(c):
        return(RandomDamageBatch(tuple(c.state.players[2].board),2,1,c.source_id,DamageKind.MINION_ABILITY),)
    scripts=dict(draw_enemy=lambda c:(Draw(2,source_id=c.source_id),),prep_enemy=prep,capture=capture,discount=discount,
        batch=batch,empty=lambda c:(RandomDamageBatch((),2,1,c.source_id,DamageKind.MINION_ABILITY),))
    for key,body in scripts.items():
        cid='k28.'+key;r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,key,CardType.MINION,health=3,battlecry=cid,metadata=meta))
    r.register_card(CardDefinition('k28.weapon','Weapon copy fixture',CardType.WEAPON,cost=5,attack=2,durability=3,metadata=meta))
    r.register_card(CardDefinition('k28.fragile','Fragile fixture',CardType.MINION,health=1,metadata=meta))
    r.register_behavior('k28.save',lambda c:tuple(Buff(i,health=1,source_id=c.source_id)
        for i in c.state.players[2].board if c.state.entities[i].card_id=='k28.fragile'))
    r.register_card(CardDefinition('k28.healer','Death buff fixture',CardType.MINION,health=1,deathrattle='k28.save',metadata=meta))
    r.register_behavior('k28.fail',lambda c:(AddToHand(c.player_id,'missing.k28'),))
    if mode:
        def watch(c):
            if c.event.kind=='card_drawn'and c.event.player_id!=2:return ()
            if mode in('move','wait_move'):
                original=CardReference.capture(c.state.entities[c.event.target_id])
                effects=(MoveCard(original,2,Zone.DECK,position='bottom',source_id=c.source_id),)
                if mode=='move':return effects
            else:effects=()
            return(RequestChoice(1,(ChoiceOption('ok','Continue',effects),),c.source_id),)
        r.register_behavior('k28.watch',watch)
        r.register_card(CardDefinition('k28.watch','Original observer',CardType.MINION,health=8,metadata=meta,
            triggers=(TriggerSpec('shield_lost'if mode=='shield'else'card_drawn','k28.watch'),)))
    return r


class TriggerSourceCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,board=(),enemy=(),deck=(YETI,)*8,enemy_hand=(),enemy_deck=(YETI,)*8,active=1,mode=None,seed=428):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,
            hero_power_card_id='HERO_08bp',mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=enemy_deck,hero_power_card_id='HERO_08bp',
                mana=40,max_mana=40,mana_cap=40)),active_player=active,seed=seed),registry(mode)if mode else self.r)
    def eid(self,g,cid,p=1,zone='board'):return next(i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def body(self,g,cid,p=1):return g.state.entities[self.eid(g,cid,p)]
    def play(self,g,cid,target=None):
        p=g.state.active_player;i=self.eid(g,cid,p,'hand');g.apply(PlayCard(p,i,target));return i
    def choose(self,g,key='ok'):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def count(self,g,cid,p=1,zone='hand'):return sum(g.state.entities[i].card_id==cid for i in getattr(g.state.players[p],zone))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));fresh=registry(self.mode)
        restored=Game.from_snapshot(saved,fresh)
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),fresh).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.for_player(p).legal_actions())
            for key in('CapturedCardCopyMaterial','next_attachment_id','draw_history','resolution_frame'):
                self.assertNotIn('"'+key+'"',public)
        return restored
    def cast_noop(self,g):return self.play(g,'k27.op.noop')

    def test_complete_source_pin_zero_attack_and_named_felbat_dependency(self):
        batch=load_batch();self.assertEqual(len(batch['cards']),7)
        self.assertEqual(self.r.card(CHO).attack,0)
        self.assertEqual((self.r.card(BAT).attack,self.r.card(BAT).health),(1,1));self.assertIn(Keyword.RUSH,self.r.card(BAT).keywords)
        for row in batch['cards']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        eredar=next(r['record']for r in batch['cards']if r['record']['id']==EREDAR)
        felbat=next(r['record']for r in batch['cards']if r['record']['id']==BAT)
        self.assertEqual(eredar['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'],felbat['dbf_id'])

    def test_each_real_root_pays_once_and_has_native_trigger(self):
        for cid in ROOTS:
            with self.subTest(card=cid):
                g=self.game((cid,));i=self.play(g,cid);card=g.registry.card(cid)
                self.assertEqual((g.state.entities[i].attack,g.state.entities[i].health),(card.attack,card.health))
                self.assertEqual(g.state.players[1].mana,40-card.cost);self.assertEqual(len(card.triggers),1)

    def test_cho_gives_original_spell_to_other_player_before_its_body(self):
        g=self.game(('k27.op.kill',),board=(CHO,),enemy=(YETI,));self.play(g,'k27.op.kill',self.eid(g,CHO))
        self.assertEqual(self.count(g,'k27.op.kill',2),1)
        events=[e.kind for e in g.events];self.assertLess(events.index('card_created'),events.index('minion_died'));self.portable(g)

    def test_cho_observes_either_player_without_changing_receiver_to_controller(self):
        g=self.game(board=(CHO,),enemy_hand=('k27.op.noop',),active=2);self.cast_noop(g)
        self.assertEqual(self.count(g,'k27.op.noop'),1);self.assertEqual(self.count(g,'k27.op.noop',2),0)

    def test_cho_countered_hand_spell_is_copied_but_automatic_is_not(self):
        g=self.game(('k27.op.noop',),board=(CHO,),enemy_hand=('EX1_287',),active=2)
        self.play(g,'EX1_287');g.apply(EndTurn(2));self.cast_noop(g)
        self.assertEqual(g.state.cast_history[-1].failure,'countered');self.assertEqual(self.count(g,'k27.op.noop',2),1)
        g=self.game(('k27.driver.generated',),board=(CHO,));self.play(g,'k27.driver.generated')
        self.assertEqual(self.count(g,'k27.op.noop',2),0);self.portable(g)

    def test_cho_repeats_once_and_backward_spell_copy_drops_local_discount(self):
        g=self.game(('k28.discount',FIRE),board=(CHO,'RLK_541'));self.play(g,'k28.discount')
        self.play(g,FIRE,g.state.players[2].hero_id)
        self.assertEqual(self.count(g,FIRE,2),1)
        copied=g.state.entities[self.eid(g,FIRE,2,'hand')];self.assertEqual(copied.cost,4);self.assertFalse(copied.enchantments)
        self.portable(g)
        g=self.game((INTELLECT,),board=(CHO,'RLK_541'));self.play(g,INTELLECT)
        self.assertEqual([c.origin for c in g.state.cast_history],['hand','repeat'])
        self.assertEqual(self.count(g,INTELLECT,2),1)

    def test_cold_selects_two_distinct_current_enemies_as_minion_ability(self):
        g=self.game(('k27.op.noop',),board=(COLD,'TIME_856'),enemy=(YETI,YETI,YETI));self.cast_noop(g)
        dealt=[e for e in g.events if e.kind=='damage_dealt']
        self.assertEqual(len(dealt),2);self.assertEqual(len({e.target_id for e in dealt}),2)
        self.assertTrue(all(e.amount==1 and dict(e.data)['damage_kind']=='minion_ability'for e in dealt));self.portable(g)

    def test_cold_one_or_two_available_enemies_use_no_selection_rng(self):
        for enemy in((),(YETI,)):
            g=self.game(('k27.op.noop',),board=(COLD,),enemy=enemy);before=g.snapshot()['rng_state'];self.cast_noop(g)
            self.assertEqual(g.snapshot()['rng_state'],before);self.assertEqual(len([e for e in g.events if e.kind=='damage_dealt']),1+len(enemy))

    def test_cold_ignores_automatic_and_triggers_once_for_whole_repeated_play(self):
        g=self.game(('k27.driver.generated',INTELLECT),board=(COLD,'RLK_541'),enemy=(YETI,))
        self.play(g,'k27.driver.generated');self.assertFalse([e for e in g.events if e.kind=='damage_dealt'])
        self.play(g,INTELLECT);self.assertEqual(len([e for e in g.events if e.kind=='damage_dealt']),2);self.portable(g)

    def test_empty_random_batch_skips_without_rng(self):
        g=self.game(('k28.empty',));before=g.snapshot()['rng_state'];self.play(g,'k28.empty')
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertEqual(sum(e.kind=='random_choice_skipped'for e in g.events),1)

    def test_distinct_damage_is_one_batch_before_either_deathrattle(self):
        g=self.game(('k28.batch',),enemy=('k28.healer','k28.fragile'));self.play(g,'k28.batch')
        self.assertFalse(g.state.players[2].board);self.assertEqual(len(g.state.death_history),2);self.portable(g)

    def test_captured_copy_keeps_drawn_minion_local_stats_and_sets_only_copy_cost(self):
        g=self.game(('k28.prep_enemy','k28.draw_enemy'),board=(KEY,));self.play(g,'k28.prep_enemy');self.play(g,'k28.draw_enemy')
        original=g.state.entities[self.eid(g,YETI,2,'hand')];copied=g.state.entities[self.eid(g,YETI,1,'hand')]
        self.assertEqual((copied.attack,copied.health,copied.cost),(6,8,1));self.assertEqual((original.attack,original.health,original.cost),(6,8,3))
        self.assertEqual(copied.origin_entity_id,original.id);self.assertTrue(set(e.id for e in copied.enchantments).isdisjoint(e.id for e in original.enchantments));self.portable(g)

    def test_alabaster_copies_original_spell_and_weapon_material(self):
        for cid in(INTELLECT,'k28.weapon'):
            g=self.game(('k28.draw_enemy',),board=(KEY,),enemy_deck=(cid,));self.play(g,'k28.draw_enemy')
            copied=g.state.entities[self.eid(g,cid,1,'hand')];self.assertEqual(copied.kind,self.r.card(cid).kind);self.assertEqual(copied.cost,1)
            if cid=='k28.weapon':self.assertEqual((copied.attack,copied.durability),(2,3))
            self.portable(g)

    def test_alabaster_copied_khadgar_rebinds_native_source_and_doubles_real_summon(self):
        cid='CORE_DAL_575'
        g=self.game(('k28.draw_enemy','CORE_EX1_506'),board=(KEY,),enemy_deck=(cid,));self.play(g,'k28.draw_enemy')
        copied=g.state.entities[self.eid(g,cid,1,'hand')];original=g.state.entities[self.eid(g,cid,2,'hand')]
        self.assertNotEqual(copied.id,original.id)
        self.assertTrue(all(a.source_id==copied.id for a in copied.abilities if a.kind=='summon_quantity'))
        self.assertTrue(all(a.source_id==original.id for a in original.abilities if a.kind=='summon_quantity'))
        self.play(g,cid);self.play(g,'CORE_EX1_506')
        self.assertEqual(len(g.state.players[1].board),6);self.portable(g)

    def test_alabaster_original_copy_survives_an_earlier_draw_reaction_moving_card(self):
        g=self.game(('k28.draw_enemy',),board=('k28.watch',KEY),mode='move');self.play(g,'k28.draw_enemy')
        self.assertEqual(self.count(g,YETI,2),0);self.assertEqual(self.count(g,YETI),1);self.portable(g)

    def test_existing_standard_conjurer_copy_uses_same_native_self_binding(self):
        cid='CORE_DAL_575'
        g=self.game(('CORE_EX1_193','CORE_EX1_506'),enemy_deck=(cid,));self.play(g,'CORE_EX1_193')
        copied=g.state.entities[self.eid(g,cid,1,'hand')]
        rows=[a for a in copied.abilities if a.kind=='summon_quantity'];self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].source_id,copied.id)
        self.play(g,cid);self.play(g,'CORE_EX1_506');self.assertEqual(len(g.state.players[1].board),5);self.portable(g)

    def test_original_draw_wait_restores_then_copies_after_source_left_hand(self):
        g=self.game(('k28.draw_enemy',),board=('k28.watch',KEY),mode='wait_move');self.play(g,'k28.draw_enemy')
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.count(g,YETI),0);restored=self.portable(g)
        for branch in(g,restored):self.choose(branch);self.assertEqual(self.count(branch,YETI),1);self.assertEqual(self.count(branch,YETI,2),0)
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_alabaster_draw_cast_copies_printed_spell_at_one_cost(self):
        g=self.game(('k28.draw_enemy',),board=(KEY,),enemy_deck=('k27.draw_cast',YETI));self.play(g,'k28.draw_enemy')
        self.assertEqual(g.state.draw_history[-1].outcome,'cast');self.assertEqual(self.count(g,'k27.draw_cast'),1)
        self.assertEqual(g.state.entities[self.eid(g,'k27.draw_cast',1,'hand')].cost,1);self.portable(g)

    def test_alabaster_does_not_copy_own_draw_burn_fatigue_or_plain_add(self):
        g=self.game((INTELLECT,),board=(KEY,));self.play(g,INTELLECT);self.assertEqual(self.count(g,YETI),2)
        g=self.game(('k28.draw_enemy',),board=(KEY,),enemy_hand=(YETI,)*10);self.play(g,'k28.draw_enemy')
        self.assertEqual(g.state.draw_history[-1].outcome,'burned');self.assertEqual(self.count(g,YETI),0)
        g=self.game(('k28.draw_enemy',),board=(KEY,),enemy_deck=());self.play(g,'k28.draw_enemy')
        self.assertEqual(g.state.draw_history[-1].outcome,'fatigue');self.assertEqual(self.count(g,YETI),0)

    def test_alabaster_full_receiver_hand_uses_existing_created_burn(self):
        g=self.game((YETI,)*10,board=(KEY,),enemy_hand=(INTELLECT,),active=2);self.play(g,INTELLECT)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(sum(e.kind=='card_burned'for e in g.events),2);self.portable(g)

    def test_eredar_two_actual_draws_summon_two_real_rush_felbats(self):
        g=self.game((INTELLECT,),board=(EREDAR,),enemy=(YETI,));self.play(g,INTELLECT)
        self.assertEqual(self.count(g,BAT,zone='board'),2)
        bat=self.eid(g,BAT)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,bat,g.state.players[2].hero_id))
        g.apply(Attack(1,bat,self.eid(g,YETI,2)));self.assertEqual(self.body(g,YETI,2).health,4);self.portable(g)

    def test_eredar_burn_and_fatigue_not_draw_events_but_draw_cast_is(self):
        g=self.game((INTELLECT,)+(YETI,)*9,board=(EREDAR,));self.play(g,INTELLECT)
        self.assertEqual([d.outcome for d in g.state.draw_history],['hand','burned']);self.assertEqual(self.count(g,BAT,zone='board'),1)
        g=self.game((INTELLECT,),board=(EREDAR,),deck=());self.play(g,INTELLECT);self.assertEqual(self.count(g,BAT,zone='board'),0)
        g=self.game((INTELLECT,),board=(EREDAR,),deck=('k27.draw_cast',YETI));self.play(g,INTELLECT)
        self.assertEqual(self.count(g,BAT,zone='board'),2);self.portable(g)

    def test_eredar_full_board_keeps_original_draws_without_summons(self):
        g=self.game((INTELLECT,),board=(EREDAR,)+(YETI,)*6);self.play(g,INTELLECT)
        self.assertEqual(self.count(g,BAT,zone='board'),0);self.assertEqual(self.count(g,YETI),2)

    def test_bolvar_friendly_shield_loss_buffs_one_hand_minion(self):
        g=self.game(('k27.op.ping',YETI),board=(BOL,SHIELD));self.play(g,'k27.op.ping',self.eid(g,SHIELD))
        held=g.state.entities[self.eid(g,YETI,1,'hand')];self.assertEqual((held.attack,held.health),(9,10));self.portable(g)

    def test_bolvar_self_shield_counts_enemy_and_nonloss_do_not(self):
        g=self.game(('k27.op.ping',YETI),board=(BOL,));self.play(g,'k27.op.ping',self.eid(g,BOL))
        self.assertEqual(g.state.entities[self.eid(g,YETI,1,'hand')].attack,9)
        g=self.game(('k27.op.ping',YETI),board=(BOL,),enemy=(SHIELD,));self.play(g,'k27.op.ping',self.eid(g,SHIELD,2))
        self.assertEqual(g.state.entities[self.eid(g,YETI,1,'hand')].attack,4)

    def test_bolvar_other_minion_silence_reports_actual_shield_loss_once(self):
        g=self.game(('k27.op.silence','k27.op.silence',YETI),board=(BOL,SHIELD));target=self.eid(g,SHIELD)
        self.play(g,'k27.op.silence',target);self.play(g,'k27.op.silence',target)
        self.assertEqual(g.state.entities[self.eid(g,YETI,1,'hand')].attack,9)
        self.assertEqual(sum(e.kind=='shield_lost'for e in g.events),1);self.portable(g)

    def test_bolvar_without_hand_minion_does_not_consume_rng(self):
        g=self.game(('k27.op.ping',),board=(BOL,SHIELD));before=g.snapshot()['rng_state']
        self.play(g,'k27.op.ping',self.eid(g,SHIELD));self.assertEqual(g.snapshot()['rng_state'],before)

    def test_moonwell_uses_original_paid_cost_including_local_discount(self):
        g=self.game(('k28.discount',FIRE),board=(MOON,));self.play(g,'k28.discount');self.play(g,FIRE,g.state.players[2].hero_id)
        self.assertEqual(g.state.play_history[-1].cost,2);self.assertEqual(self.body(g,MOON).attack,3);self.portable(g)

    def test_moonwell_counts_personal_play_once_and_not_automatic(self):
        g=self.game(('k27.driver.generated',INTELLECT),board=(MOON,'RLK_541'));self.play(g,'k27.driver.generated')
        self.assertEqual(self.body(g,MOON).attack,1);self.play(g,INTELLECT);self.assertEqual(self.body(g,MOON).attack,4);self.portable(g)

    def test_captured_copy_in_private_choice_restores_and_failed_choice_rolls_back(self):
        g=self.game(('k28.capture',),deck=('k28.weapon',));self.play(g,'k28.capture');restored=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        for branch in(g,restored):self.choose(branch);self.assertEqual(self.count(branch,'k28.weapon'),1)
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_new_copy_bounds_and_random_batch_shapes_are_strict(self):
        g=self.game();source=g.state.entities[g.state.players[1].deck[0]];material=CapturedCardCopyMaterial.capture(g.state,source)
        for value in(True,0,-1):
            with self.assertRaises(ValueError):replace(material,next_attachment_id=value)
        for count in(True,0,-1,1.5):
            with self.assertRaises(ValueError):RandomDamageBatch((),count,1)
        with self.assertRaises(ValueError):RandomDamageBatch((1,1),2,1)
        before=g.snapshot()
        for p in(1,2):g.for_player(p).legal_actions();g.observe(p)
        self.assertEqual(g.snapshot(),before)

    def test_future_captured_copy_material_in_waiting_snapshot_is_rejected(self):
        g=self.game(('k28.capture',));self.play(g,'k28.capture');saved=g.snapshot()
        keys={'origin','local','components','durability','galakrond_invocations','preparation','jade_size','turn','action','next_attachment_id'}
        def find(value):
            if isinstance(value,dict):
                if set(value)==keys:return value
                for child in value.values():
                    result=find(child)
                    if result is not None:return result
            elif isinstance(value,list):
                for child in value:
                    result=find(child)
                    if result is not None:return result
        material=find(saved);self.assertIsNotNone(material)
        material['next_attachment_id']=g.state.next_attachment_id+100
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())
