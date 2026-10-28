"""Eleven real secret effects and the complete unfiltered reference inventory."""
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import past_secret_base_effects as native
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario,UseHeroPower
from hs_sim.engine.effects import (Buff,ChoiceOption,Damage,Destroy,Draw,GainArmor,InvokeBehavior,
    RandomDamage,RequestChoice,Transform)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,SecretSpec,SpellSchool,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.local_pool_format import build_cn37_local_pool_format

SPIRIT,MATRIX,TRICKS,SURRENDER,EYE,REPENT,SNIPE,SNIPE2,PLATE,WISDOM,DART=native.LEAVES
P='k634.';UNIT,SMALL,SHIELD,FILL,WATCH,POWER,BC,DEAD,CHANGE=(P+x for x in ('unit','small','shield','fill','watch','power','bc','dead','change'))
NOOP,HIT,AREA,ARMOR,AUTO,FAIL,COUNTER=(P+x for x in ('noop','hit','area','armor','auto','fail','counter'))


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_past_secret_base_effects(r)
    r.register_behavior(NOOP,lambda c:())
    r.register_behavior(HIT,lambda c:(Damage(c.target_id,5,c.source_id,DamageKind.SPELL),))
    r.register_behavior(AREA,lambda c:tuple(Damage(i,3,c.source_id,DamageKind.SPELL) for i in c.state.players[3-c.player_id].board))
    r.register_behavior(ARMOR,lambda c:(GainArmor(c.player_id,3),))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,NOOP,c.source_id),))
    for cid in (NOOP,HIT,AREA,ARMOR,AUTO):
        extra={'targeting':TargetSpec(zones=(Zone.BOARD,Zone.HERO),kinds=(CardType.MINION,CardType.HERO))} if cid==HIT else {}
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,spell_school=SpellSchool.ARCANE,metadata=metadata(tribes=()),**extra))
    r.register_behavior(BC,lambda c:(Buff(c.source_id,1,3,c.source_id),))
    r.register_behavior(DEAD,lambda c:(Destroy(c.source_id,c.source_id),))
    r.register_behavior(CHANGE,lambda c:(Transform(c.source_id,FILL),))
    for cid,attack,health,kw in ((UNIT,3,10,()),(SMALL,1,1,()),(SHIELD,3,10,(Keyword.DIVINE_SHIELD,)),(FILL,1,10,()),
            (WATCH,0,30,()),(POWER,0,10,()),(BC,3,10,()),(DEAD,3,10,()),(CHANGE,3,10,())):
        extra={'battlecry':cid} if cid in (BC,DEAD,CHANGE) else {}
        if cid==POWER:extra['spell_damage']=2
        if cid==WATCH and mode!='normal':extra['triggers']=(TriggerSpec('card_drawn' if mode=='draw' else 'secret_revealed',P+'wait'),)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=attack,health=health,keywords=kw,metadata=metadata(tribes=()),**extra))
    r.register_behavior(COUNTER,lambda c:(CounterSpell(c.window.id),))
    r.register_secret_condition(COUNTER,lambda c:bool(c.window and c.window.kind=='spell' and c.window.player_id!=c.player_id))
    r.register_card(CardDefinition(COUNTER,COUNTER,CardType.SPELL,keywords=(Keyword.SECRET,),
        secret=SecretSpec(COUNTER,('card_committed',),COUNTER,COUNTER),metadata=metadata(tribes=())))
    def fail(c):raise ResolutionError('K634 deliberate choice/RNG rollback')
    r.register_behavior(FAIL,fail)
    def wait(c):
        e=c.event;source=c.state.entities.get(e.source_id)
        if source is None or source.card_id not in native.LEAVES or mode=='draw' and e.player_id!=c.player_id:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(P+'wait',wait);r.validate();r.freeze();return r


@lru_cache(None)
def host():return build_cn37_local_pool_format().registry


class PastSecretBaseTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,hand=(),*,board=(),enemy=(),other_hand=(),deck=(FILL,)*10,player=1,mode='normal'):
        self.mode=mode
        setups=[PlayerSetup('mage.hero',hand=hand,board=board,deck=deck,hero_power_card_id='mage.power',mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('warrior.hero',hand=other_hand,board=enemy,deck=(FILL,)*10,hero_power_card_id='warrior.power',mana=40,max_mana=40,mana_cap=40)]
        if player==2:setups.reverse()
        return Game.from_scenario(Scenario(tuple(setups),active_player=player,seed=91),registry(mode))
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def active(self,g,p=1):return [g.state.entities[i].card_id for i in g.state.players[p].secrets]
    def arm(self,g,cid,p=1):source=self.play(g,cid,player=p);g.apply(EndTurn(p));return source
    def settle(self,g):
        while g.state.pending_choice is not None:
            g=self.portable(g);saved=g.snapshot()
            with self.assertRaisesRegex(ResolutionError,'K634'):self.choose(g,'fail')
            self.assertEqual(g.snapshot(),saved);self.choose(g)
        return g
    def hit(self,g,target,p=2):self.play(g,HIT,target,player=p)

    def test_all_eleven_complete_faces_and_twenty_two_primary_checks(self):
        d=native.load_batch();rows={x['record']['id']:x['record'] for x in d['dependencies']}
        for o in d['official_observations']:batch.check_face(rows[o['card_id']],o['face'],o['locale'])
        self.assertEqual(tuple(rows),native.LEAVES);self.assertFalse(d['source_scope_bound'])

    def test_unfiltered_full72_reference_preserves_roles_order_weights_and_name_conflict(self):
        d=native.load_batch();ref=batch.read(native.ROOT/d['reference_document']);self.assertEqual(len(ref['candidate_ids']),72)
        self.assertEqual([x['record']['id'] for x in ref['candidate_records']],ref['candidate_ids'])
        self.assertEqual(ref['candidate_weights'],[1]*72);self.assertEqual(ref['candidate_roles'],['ordinary']*72)
        self.assertEqual({x['record']['tags']['CLASS'] for x in ref['candidate_records']},{3,4,5,7})
        self.assertFalse(ref['runtime_bindings_added']);self.assertFalse(ref['membership_uses_executable_coverage'])
        rows={x['record']['id']:x['record'] for x in (*ref['candidate_records'],ref['source_producer'])}
        for x in ref['candidate_records']:self.assertEqual(batch.canonical(x['record']),x['record_sha256'])
        self.assertEqual(len(ref['official_observations']),145)
        for o in ref['official_observations']:batch.check_face(rows[o['card_id']],o['face'],o['locale'])
        conflict=ref['conflicting_official_observations'][0];self.assertEqual(conflict['card_id'],'LOE_027')
        with self.assertRaisesRegex(ValueError,'name drift'):
            batch.check_face(rows['LOE_027'],conflict['complete_cached_observation']['face'],'zh_CN')
        self.assertNotIn('WON_040',ref['candidate_ids']);self.assertNotIn('SECRET',ref['source_producer']['record']['tags'])

    def test_all_real_costs_hidden_payment_and_duplicate_secret_atomicity(self):
        for cid in native.LEAVES:
            g=self.game((cid,cid));cost=g.registry.card(cid).cost;source=self.play(g,cid)
            self.assertEqual(g.state.players[1].mana,40-cost);self.assertIn(source,g.state.players[1].secrets)
            self.assertNotIn(cid,json.dumps(g.for_player(2).observe()));saved=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,cid)
            self.assertEqual(g.snapshot(),saved)

    def test_competitive_spirit_owner_start_buffs_all_current_friendly_minions(self):
        g=self.game((SPIRIT,),board=(UNIT,FILL),enemy=(UNIT,));self.arm(g,SPIRIT)
        self.assertIn(SPIRIT,self.active(g));g.apply(EndTurn(2))
        self.assertEqual([(g.state.entities[i].attack,g.state.entities[i].health) for i in g.state.players[1].board],[(4,11),(2,11)])
        self.assertEqual(self.entity(g,UNIT,2,'board').health,10);self.assertFalse(self.active(g))

    def test_competitive_spirit_empty_board_keeps_secret(self):
        g=self.game((SPIRIT,));self.arm(g,SPIRIT);g.apply(EndTurn(2));self.assertIn(SPIRIT,self.active(g))

    def test_auto_defense_matrix_shields_original_attacked_friendly_minion(self):
        g=self.game((MATRIX,),board=(UNIT,),enemy=(UNIT,));self.arm(g,MATRIX)
        defender=self.entity(g,UNIT,1,'board').id;attacker=self.entity(g,UNIT,2,'board').id
        g.apply(Attack(2,attacker,defender));self.assertEqual(g.state.entities[defender].health,10)
        self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[defender].keywords);self.assertFalse(self.active(g))

    def test_matrix_hero_target_and_already_shielded_minion_keep_secret(self):
        for board in ((),(SHIELD,)):
            g=self.game((MATRIX,),board=board,enemy=(UNIT,));self.arm(g,MATRIX)
            target=self.entity(g,SHIELD,1,'board').id if board else g.state.players[1].hero_id
            g.apply(Attack(2,self.entity(g,UNIT,2,'board').id,target));self.assertIn(MATRIX,self.active(g))

    def test_never_surrender_buffs_before_original_spell_payload(self):
        g=self.game((SURRENDER,),board=(UNIT,),other_hand=(AREA,));self.arm(g,SURRENDER);self.play(g,AREA,player=2)
        target=self.entity(g,UNIT,1,'board');self.assertEqual((target.max_health,target.health),(12,9));self.assertFalse(self.active(g))

    def test_dirty_tricks_draws_two_after_successful_enemy_cast(self):
        g=self.game((TRICKS,),other_hand=(NOOP,));self.arm(g,TRICKS);self.play(g,NOOP,player=2)
        self.assertEqual(len(g.state.players[1].hand),2);self.assertFalse(self.active(g))

    def test_countered_cast_triggers_started_surrender_but_not_completed_consumers(self):
        for cid in (SURRENDER,TRICKS,PLATE):
            g=self.game((COUNTER,cid),board=(UNIT,),enemy=(UNIT,),other_hand=(NOOP,))
            self.play(g,COUNTER);self.arm(g,cid);self.play(g,NOOP,player=2)
            if cid==SURRENDER:self.assertEqual(self.entity(g,UNIT,1,'board').health,12);self.assertNotIn(cid,self.active(g))
            else:self.assertIn(cid,self.active(g))

    def test_completed_automatic_cast_uses_same_actual_secret_path(self):
        g=self.game((TRICKS,),other_hand=(AUTO,));self.arm(g,TRICKS);self.play(g,AUTO,player=2)
        self.assertEqual(len(g.state.players[1].hand),2);self.assertEqual(sum(e.kind=='secret_revealed' for e in g.events),1)

    def test_pressure_plate_uses_real_random_enemy_minion_and_ignores_heroes(self):
        g=self.game((PLATE,),enemy=(UNIT,FILL),other_hand=(NOOP,));self.arm(g,PLATE);self.play(g,NOOP,player=2)
        self.assertEqual(len(g.state.players[2].board),1);self.assertEqual(self.hero(g,2).health,30);self.assertFalse(self.active(g));self.portable(g)

    def test_pressure_plate_empty_enemy_board_keeps_secret_and_rng(self):
        g=self.game((PLATE,),other_hand=(NOOP,));self.arm(g,PLATE);rng=g.snapshot()['rng_state'];self.play(g,NOOP,player=2)
        self.assertIn(PLATE,self.active(g));self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_eye_for_eye_repeats_actual_armor_and_health_damage(self):
        g=self.game((ARMOR,EYE),other_hand=(HIT,));self.play(g,ARMOR);self.arm(g,EYE);self.hit(g,g.state.players[1].hero_id)
        self.assertEqual((self.hero(g).health,self.hero(g).armor,self.hero(g,2).health),(28,0,25));self.assertFalse(self.active(g))

    def test_eye_for_eye_does_not_react_to_minion_damage_and_uses_ordinary_spell_power(self):
        g=self.game((EYE,),board=(UNIT,POWER),other_hand=(HIT,HIT));self.arm(g,EYE)
        self.hit(g,self.entity(g,UNIT,1,'board').id);self.assertIn(EYE,self.active(g))
        self.hit(g,g.state.players[1].hero_id);self.assertEqual(self.hero(g,2).health,23)

    def test_repentance_sets_actual_played_body_health_after_battlecry(self):
        g=self.game((REPENT,),other_hand=(BC,));self.arm(g,REPENT);self.play(g,BC,player=2)
        unit=self.entity(g,BC,2,'board');self.assertEqual((unit.attack,unit.health,unit.max_health),(4,1,1));self.assertFalse(self.active(g))

    def test_repentance_one_health_or_dead_play_keeps_secret(self):
        for cid in (SMALL,DEAD):
            g=self.game((REPENT,),other_hand=(cid,));self.arm(g,REPENT);self.play(g,cid,player=2);self.assertIn(REPENT,self.active(g))

    def test_in_place_battlecry_transform_keeps_original_play_residence(self):
        g=self.game((REPENT,),other_hand=(CHANGE,));self.arm(g,REPENT);self.play(g,CHANGE,player=2)
        self.assertEqual(self.entity(g,FILL,2,'board').health,1);self.assertFalse(self.active(g))

    def test_both_snipe_faces_deal_current_printed_six_damage(self):
        for cid in (SNIPE,SNIPE2):
            g=self.game((cid,),other_hand=(UNIT,));self.arm(g,cid);self.play(g,UNIT,player=2)
            self.assertEqual(self.entity(g,UNIT,2,'board').health,4);self.assertFalse(self.active(g))

    def test_snipe_reprint_shares_secret_key_and_deck_identity(self):
        g=self.game((SNIPE,SNIPE2));self.play(g,SNIPE);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,SNIPE2)
        self.assertEqual(g.snapshot(),saved);self.assertEqual(g.registry.card(SNIPE).metadata.deck_identity,g.registry.card(SNIPE2).metadata.deck_identity)

    def test_hidden_wisdom_counts_third_actual_hand_play_once(self):
        g=self.game((WISDOM,),other_hand=(NOOP,NOOP,UNIT));self.arm(g,WISDOM)
        self.play(g,NOOP,player=2);self.play(g,NOOP,player=2);self.assertIn(WISDOM,self.active(g))
        self.play(g,UNIT,player=2);self.assertFalse(self.active(g));self.assertEqual(len(g.state.players[1].hand),2)

    def test_hidden_wisdom_generated_casts_do_not_become_extra_hand_plays(self):
        g=self.game((WISDOM,),other_hand=(AUTO,AUTO));self.arm(g,WISDOM);self.play(g,AUTO,player=2);self.play(g,AUTO,player=2)
        self.assertIn(WISDOM,self.active(g));self.assertEqual(len([r for r in g.state.play_history if r.player_id==2]),2)

    def test_dart_trap_uses_actual_manual_opponent_power_then_random_enemy(self):
        g=self.game((DART,),enemy=(UNIT,));self.arm(g,DART);g.apply(UseHeroPower(2,g.state.players[2].hero_power_ids[0]))
        self.assertEqual(self.hero(g,2).health+self.entity(g,UNIT,2,'board').health,35);self.assertFalse(self.active(g));self.portable(g)

    def test_own_turn_power_and_cast_do_not_consume_opponent_secrets(self):
        g=self.game((DART,TRICKS,NOOP));self.play(g,DART);self.play(g,TRICKS);g.apply(UseHeroPower(1,g.state.players[1].hero_power_ids[0]));self.play(g,NOOP)
        self.assertEqual(set(self.active(g)),{DART,TRICKS})

    def test_draw_effects_use_normal_burn_and_fatigue(self):
        g=self.game((TRICKS,)+(FILL,)*9,other_hand=(NOOP,));self.arm(g,TRICKS);self.play(g,NOOP,player=2)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertTrue(any(e.kind=='card_burned' for e in g.events))
        g=self.game((TRICKS,),deck=(),other_hand=(NOOP,));self.arm(g,TRICKS);self.play(g,NOOP,player=2)
        self.assertEqual(self.hero(g).health,27);self.assertFalse(self.active(g))

    def test_actual_secret_reveal_waits_restore_each_distinct_entry_family(self):
        for cid in (SPIRIT,MATRIX,SURRENDER,TRICKS,SNIPE,EYE,DART):
            g=self.game((cid,),board=(WATCH,UNIT),enemy=(UNIT,),other_hand=(UNIT,NOOP,HIT),mode='reveal');self.arm(g,cid)
            if cid==SPIRIT:g.apply(EndTurn(2))
            elif cid==MATRIX:g.apply(Attack(2,self.entity(g,UNIT,2,'board').id,self.entity(g,UNIT,1,'board').id))
            elif cid in (SURRENDER,TRICKS):self.play(g,NOOP,player=2)
            elif cid==SNIPE:self.play(g,UNIT,player=2)
            elif cid==EYE:self.hit(g,g.state.players[1].hero_id)
            else:g.apply(UseHeroPower(2,g.state.players[2].hero_power_ids[0]))
            self.assertIsNotNone(g.state.pending_choice);g=self.settle(g);self.assertNotIn(cid,self.active(g));self.portable(g)

    def test_actual_first_draw_wait_keeps_original_two_draw_plan(self):
        g=self.game((TRICKS,),board=(WATCH,),other_hand=(NOOP,),mode='draw');self.arm(g,TRICKS);self.play(g,NOOP,player=2)
        self.assertIsNotNone(g.state.pending_choice);g=self.settle(g);self.assertEqual(len(g.state.players[1].hand),2);self.portable(g)

    def test_second_seat_cast_and_draw_use_actual_secret_owner(self):
        g=self.game((TRICKS,),other_hand=(NOOP,),player=2);self.arm(g,TRICKS,2);self.play(g,NOOP,player=1)
        self.assertEqual(len(g.state.players[2].hand),2);self.assertFalse(self.active(g,2))

    def test_complete_local_host_native_snipe_and_still_closed_disco_source(self):
        r=host();self.assertTrue(set(native.LEAVES)<=set(r.cards));self.assertNotIn('WON_040',r.cards)
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(SNIPE,),mana=20,max_mana=20,mana_cap=20),
            PlayerSetup('HERO_08',hand=('TTN_480t1',),deck=('TTN_480t1',)*3,mana=20,max_mana=20,mana_cap=20))),r)
        self.play(g,SNIPE);g.apply(EndTurn(1));self.play(g,'TTN_480t1',player=2)
        self.assertFalse(g.state.players[2].board);self.assertFalse(g.state.players[1].secrets)


if __name__=='__main__':unittest.main()
