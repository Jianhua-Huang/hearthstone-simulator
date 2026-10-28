"""Real original-event consumers; no Game is executed during import."""
from dataclasses import asdict,replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import past_secret_event_effects as native
from hs_sim.cards.fixed_companion_cards import register_fixed_companion_cards
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import (Buff,ChoiceOption,Damage,DamageBatch,Destroy,GrantKeyword,InvokeBehavior,
    RandomDamage,RequestChoice,Summon)
from hs_sim.engine.health_loss import LoseHealth
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,SecretSpec,SummonQuantitySpec,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError

CACHE,RECKON,CAGE,AVENGE,EVADE,MOTION,BIN,BAIT,JUDGMENT=native.LEAVES
P='k636.';UNIT,SMALL,FILL,WATCH,DOUBLE,DEAD,BOLT,MULTI,SHIELD=(P+x for x in ('unit','small','fill','watch','double','dead','bolt','multi','shield'))
NOOP,HURT,KILL,GET,AUTO,LOSS,WEAPON,COUNTER,FAIL=(P+x for x in ('noop','hurt','kill','get','auto','loss','weapon','counter','fail'))
SWEEP=P+'sweep'
SLEEPER=P+'sleeper'


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();register_fixed_companion_cards(r);native.register_past_secret_event_effects(r)
    for cid in (NOOP,HURT,KILL,GET,AUTO,LOSS,SWEEP):
        effects={NOOP:lambda c:(),HURT:lambda c:(Damage(c.target_id,2,c.source_id),),
            KILL:lambda c:(Destroy(c.target_id,c.source_id),),GET:lambda c:(Summon(c.player_id,UNIT),),
            AUTO:lambda c:(CastSpell(c.player_id,NOOP,c.source_id),),LOSS:lambda c:(LoseHealth(c.target_id,2,c.source_id),),
            SWEEP:lambda c:(DamageBatch(tuple(Damage(i,2,c.source_id) for i in c.state.players[3-c.player_id].board)),)}
        r.register_behavior(cid,effects[cid]);extra={}
        if cid in (HURT,KILL,LOSS):extra['targeting']=TargetSpec(zones=(Zone.BOARD,Zone.HERO),kinds=(CardType.MINION,CardType.HERO))
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata(tribes=()),**extra))
    r.register_behavior(DEAD,lambda c:(Destroy(c.source_id,c.source_id),))
    r.register_behavior(BOLT,lambda c:(Damage(c.state.players[3-c.player_id].hero_id,3,c.source_id,DamageKind.MINION_ABILITY),))
    r.register_behavior(MULTI,lambda c:(DamageBatch(tuple(Damage(c.state.players[3-c.player_id].hero_id,2,c.source_id,DamageKind.MINION_ABILITY) for _ in range(2))),))
    for cid,attack,health in ((UNIT,3,10),(SMALL,1,1),(FILL,0,8),(WATCH,0,30),(DOUBLE,0,8),(DEAD,3,3),(BOLT,1,8),(MULTI,1,8),(SHIELD,3,10)):
        extra={}
        if cid in (DEAD,BOLT,MULTI):extra['battlecry']=cid
        if cid==DOUBLE:extra['summon_quantities']=(SummonQuantitySpec(),)
        if cid==SHIELD:extra['keywords']=(Keyword.DIVINE_SHIELD,)
        if cid==WATCH and mode!='normal':extra['triggers']=(TriggerSpec({'draw':'card_drawn','summon':'minion_summoned'}.get(mode,'secret_revealed'),P+'watch'),)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=attack,health=health,metadata=metadata(tribes=()),**extra))
    r.register_card(CardDefinition(SLEEPER,SLEEPER,CardType.MINION,attack=2,health=5,dormant_turns=3,metadata=metadata(tribes=())))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,cost=1,attack=2,durability=3,metadata=metadata(tribes=())))
    r.register_secret_condition(COUNTER,lambda c:bool(c.window and c.window.kind=='spell' and c.window.player_id!=c.player_id))
    r.register_behavior(COUNTER,lambda c:(CounterSpell(c.window.id),))
    r.register_card(CardDefinition(COUNTER,COUNTER,CardType.SPELL,keywords=(Keyword.SECRET,),
        secret=SecretSpec(COUNTER,('card_committed',),COUNTER,COUNTER),metadata=metadata(tribes=())))
    def fail(c):raise ResolutionError('K636 deliberate choice/RNG rollback')
    def watch(c):
        if mode=='draw' and c.event.player_id!=c.player_id:return ()
        if mode=='summon':
            e=c.state.entities.get(c.event.target_id)
            if e is None or e.controller!=c.player_id or e.card_id not in native.EXISTING:return ()
        if mode not in ('draw','summon'):
            e=c.state.entities.get(c.event.source_id)
            if e is None or e.card_id not in native.LEAVES:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(FAIL,fail);r.register_behavior(P+'watch',watch);r.validate();r.freeze();return r


@lru_cache(None)
def host():return build_cn37_local_pool_format().registry


class PastSecretEventEffectTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,hand=(),*,board=(),enemy=(),other_hand=(),deck=(FILL,)*12,player=1,mode='normal',seed=107,other_weapon=None):
        self.mode=mode
        setups=[PlayerSetup('mage.hero',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('warrior.hero',hand=other_hand,board=enemy,deck=(FILL,)*12,weapon_card_id=other_weapon,mana=40,max_mana=40,mana_cap=40)]
        if player==2:setups.reverse()
        return Game.from_scenario(Scenario(tuple(setups),active_player=player,seed=seed),registry(mode))
    def arm(self,g,cid,p=1):eid=self.play(g,cid,player=p);g.apply(EndTurn(p));return eid
    def secrets(self,g,p=1):return [g.state.entities[i].card_id for i in g.state.players[p].secrets]
    def bodies(self,g,cid,p=1):return [g.state.entities[i] for i in g.state.players[p].board if g.state.entities[i].card_id==cid]
    def attack(self,g,*,target=None,p=2):g.apply(Attack(p,self.entity(g,UNIT,p,'board').id,target or g.state.players[3-p].hero_id))
    def settle(self,g):
        while g.state.pending_choice:self.choose(g)
    def portable_wait(self,g):
        saved=g.snapshot();restored=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.settle(g);self.settle(restored);self.assertEqual(g.snapshot(),restored.snapshot())

    def test_full_twelve_rows_eighteen_faces_and_three_unchanged_companions(self):
        d=native.load_batch();self.assertEqual((len(d['dependencies']),len(d['existing_dependencies']),len(d['official_observations'])),(9,3,18))
        for row in d['existing_dependencies']:self.assertEqual(batch.canonical(asdict(registry().card(row['record']['id']))),row['definition_sha256'])
        self.assertFalse(d['source_scope_bound']);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_all_nine_paid_hidden_secrets_and_duplicate_prevention(self):
        for cid in native.LEAVES:
            with self.subTest(card=cid):
                g=self.game((cid,cid));mana=g.state.players[1].mana;self.play(g,cid)
                self.assertEqual(g.state.players[1].mana,mana-registry().card(cid).cost)
                saved=g.snapshot()
                with self.assertRaises(IllegalAction):self.play(g,cid)
                self.assertEqual(g.snapshot(),saved);self.assertNotIn(cid,json.dumps(g.for_player(2).observe()))

    def test_cache_buffs_only_original_hand_minion_after_even_dead_battlecry(self):
        for played in (UNIT,DEAD):
            g=self.game((CACHE,FILL,NOOP,WEAPON),other_hand=(played,));self.arm(g,CACHE);self.play(g,played,player=2)
            e=self.entity(g,FILL);self.assertEqual((e.attack,e.max_health),(2,10));self.assertNotIn(CACHE,self.secrets(g))
            owner=next(x for x in g.for_player(2).observe()['observation']['players'] if x['id']==1)
            self.assertTrue(all(x.get('card_id') is None for x in owner['hand']))

    def test_cache_keeps_secret_for_empty_minion_hand_and_ignores_generated_summons(self):
        g=self.game((CACHE,NOOP),other_hand=(UNIT,));self.arm(g,CACHE);self.play(g,UNIT,player=2);self.assertIn(CACHE,self.secrets(g))
        g=self.game((CACHE,FILL),other_hand=(GET,AUTO));self.arm(g,CACHE);self.play(g,GET,player=2);self.play(g,AUTO,player=2)
        self.assertIn(CACHE,self.secrets(g));self.assertEqual(self.entity(g,FILL).attack,0)

    def test_reckoning_destroys_original_enemy_attacker_after_three_actual_damage(self):
        g=self.game((RECKON,),enemy=(UNIT,));self.arm(g,RECKON);attacker=self.entity(g,UNIT,2,'board').id;self.attack(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27);self.assertEqual(g.state.entities[attacker].zone,Zone.GRAVEYARD)
        self.assertNotIn(RECKON,self.secrets(g));self.portable(g)

    def test_reckoning_uses_minion_ability_source_and_never_sums_small_packets(self):
        g=self.game((RECKON,),other_hand=(BOLT,));self.arm(g,RECKON);eid=self.play(g,BOLT,player=2)
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.portable(g)
        g=self.game((RECKON,),other_hand=(MULTI,));self.arm(g,RECKON);self.play(g,MULTI,player=2);self.assertIn(RECKON,self.secrets(g))

    def test_reckoning_ignores_spell_source_and_prevented_minion_damage(self):
        g=self.game((RECKON,),other_hand=(HURT,HURT));self.arm(g,RECKON)
        for _ in range(2):self.play(g,HURT,g.state.players[1].hero_id,player=2)
        self.assertIn(RECKON,self.secrets(g))
        g=self.game((RECKON,),board=(SHIELD,),enemy=(UNIT,));self.arm(g,RECKON);self.attack(g,target=self.entity(g,SHIELD,1,'board').id)
        self.assertIn(RECKON,self.secrets(g));self.assertEqual(len(self.bodies(g,UNIT,2)),1)

    def test_cages_owner_start_requires_two_minions_and_keeps_full_board_secret(self):
        g=self.game((CAGE,),board=(UNIT,));self.arm(g,CAGE);g.apply(EndTurn(2));self.assertIn(CAGE,self.secrets(g))
        g=self.game((CAGE,),board=(UNIT,FILL));self.arm(g,CAGE);self.assertIn(CAGE,self.secrets(g));g.apply(EndTurn(2))
        self.assertNotIn(CAGE,self.secrets(g));self.assertEqual(len(g.state.players[1].board),3);self.portable(g)
        g=self.game((CAGE,),board=(FILL,)*7);self.arm(g,CAGE);g.apply(EndTurn(2));self.assertIn(CAGE,self.secrets(g))

    def test_cages_generates_all_three_real_companions_with_original_combat_behavior(self):
        seen=set()
        for seed in range(1,25):
            g=self.game((CAGE,),board=(UNIT,FILL),enemy=(UNIT,),seed=seed);self.arm(g,CAGE);g.apply(EndTurn(2))
            e=next(g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id in native.EXISTING)
            if e.card_id in seen:continue
            seen.add(e.card_id)
            if e.card_id=='NEW1_034':g.apply(Attack(1,e.id,g.state.players[2].hero_id));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,26)
            elif e.card_id=='NEW1_033':self.assertEqual(self.entity(g,UNIT,1,'board').attack,4)
            else:
                g.apply(EndTurn(1))
                with self.assertRaises(IllegalAction):self.attack(g)
            self.portable(g)
            if seen==set(native.EXISTING):break
        self.assertEqual(seen,set(native.EXISTING))

    def test_cages_reuses_shared_quantity_expansion(self):
        g=self.game((CAGE,),board=(UNIT,DOUBLE));self.arm(g,CAGE);g.apply(EndTurn(2))
        ids=[g.state.entities[i].card_id for i in g.state.players[1].board if g.state.entities[i].card_id in native.EXISTING]
        self.assertEqual(len(ids),2);self.assertEqual(ids[0],ids[1]);self.portable(g)

    def test_cages_counts_controlled_dormant_minion_without_awakening_it(self):
        g=self.game((CAGE,),board=(UNIT,SLEEPER));self.arm(g,CAGE);self.assertFalse(self.entity(g,SLEEPER,1,'board').active)
        g.apply(EndTurn(2));self.assertNotIn(CAGE,self.secrets(g));self.assertFalse(self.entity(g,SLEEPER,1,'board').active)
        self.assertEqual(len(g.state.players[1].board),3)

    def test_avenge_buffs_only_living_survivor_and_empty_simultaneous_batch_keeps_secret(self):
        g=self.game((AVENGE,),board=(UNIT,FILL),other_hand=(KILL,));self.arm(g,AVENGE);self.play(g,KILL,self.entity(g,UNIT,1,'board').id,player=2)
        e=self.entity(g,FILL,1,'board');self.assertEqual((e.attack,e.max_health),(3,10));self.portable(g)
        g=self.game((AVENGE,),board=(SMALL,SMALL),other_hand=(SWEEP,));self.arm(g,AVENGE);self.play(g,SWEEP,player=2)
        self.assertEqual(len(g.state.players[1].board),0)
        self.assertIn(AVENGE,self.secrets(g))

    def test_avenge_does_not_trigger_for_enemy_death(self):
        g=self.game((AVENGE,),board=(FILL,),other_hand=(DEAD,));self.arm(g,AVENGE);self.play(g,DEAD,player=2)
        self.assertIn(AVENGE,self.secrets(g));self.assertEqual(self.entity(g,FILL,1,'board').attack,0)

    def test_evasion_follows_actual_damage_then_protects_later_packets_and_expires(self):
        g=self.game((EVADE,),other_hand=(HURT,BOLT));self.arm(g,EVADE);hero=g.state.players[1].hero_id
        self.play(g,HURT,hero,player=2);self.assertEqual(g.state.entities[hero].health,28);self.assertIn(Keyword.IMMUNE,g.state.entities[hero].keywords)
        self.play(g,BOLT,player=2);self.assertEqual(g.state.entities[hero].health,28);self.portable(g)
        g.apply(EndTurn(2));self.assertNotIn(Keyword.IMMUNE,g.state.entities[hero].keywords)

    def test_evasion_ignores_direct_health_loss(self):
        g=self.game((EVADE,),other_hand=(LOSS,));self.arm(g,EVADE);self.play(g,LOSS,g.state.players[1].hero_id,player=2)
        self.assertIn(EVADE,self.secrets(g));self.assertNotIn(Keyword.IMMUNE,g.state.entities[g.state.players[1].hero_id].keywords)

    def test_motion_counts_third_actual_hand_play_not_nested_automatic_cast(self):
        g=self.game((MOTION,),other_hand=(AUTO,NOOP,NOOP));self.arm(g,MOTION);hero=g.state.players[2].hero_id
        self.play(g,AUTO,player=2);self.play(g,NOOP,player=2);self.assertIn(MOTION,self.secrets(g));self.assertEqual(g.state.entities[hero].health,30)
        self.play(g,NOOP,player=2);self.assertNotIn(MOTION,self.secrets(g));self.assertEqual(g.state.entities[hero].health,24);self.portable(g)

    def test_motion_counts_countered_physical_play(self):
        g=self.game((MOTION,COUNTER),other_hand=(NOOP,NOOP,NOOP));self.play(g,COUNTER);self.arm(g,MOTION)
        for _ in range(3):self.play(g,NOOP,player=2)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,24);self.assertNotIn(MOTION,self.secrets(g))

    def test_bin_draws_other_two_printed_kinds_for_minion_spell_and_weapon(self):
        for played,kinds in ((UNIT,(CardType.SPELL,CardType.WEAPON)),(NOOP,(CardType.MINION,CardType.WEAPON)),(WEAPON,(CardType.MINION,CardType.SPELL))):
            g=self.game((BIN,),deck=(FILL,NOOP,WEAPON),other_hand=(played,));self.arm(g,BIN)
            before=set(g.state.players[1].hand);self.play(g,played,player=2)
            self.assertEqual(tuple(g.state.entities[i].kind for i in g.state.players[1].hand if i not in before),kinds);self.assertNotIn(BIN,self.secrets(g));self.portable(g)

    def test_bin_generated_cast_does_not_add_physical_play_and_empty_slots_do_not_fatigue(self):
        g=self.game((BIN,),deck=(FILL,FILL,WEAPON,WEAPON),other_hand=(AUTO,));self.arm(g,BIN);self.play(g,AUTO,player=2)
        self.assertEqual(len(g.state.players[1].hand),2);self.portable(g)
        g=self.game((BIN,),deck=(),other_hand=(AUTO,));self.arm(g,BIN);before=g.state.entities[g.state.players[1].hero_id].health
        self.play(g,AUTO,player=2);self.assertNotIn(BIN,self.secrets(g));self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,before)
        self.portable(g)

    def test_bait_buffs_original_attacked_friendly_minion_before_combat(self):
        g=self.game((BAIT,),board=(UNIT,),enemy=(UNIT,));self.arm(g,BAIT);target=self.entity(g,UNIT,1,'board').id;self.attack(g,target=target)
        e=g.state.entities[target];self.assertEqual((e.attack,e.max_health,e.health),(6,13,10));self.portable(g)
        g=self.game((BAIT,),board=(UNIT,),enemy=(UNIT,));self.arm(g,BAIT);self.attack(g);self.assertIn(BAIT,self.secrets(g))

    def test_judgment_sets_current_enemy_attacker_to_one_one_before_actual_damage(self):
        g=self.game((JUDGMENT,),enemy=(UNIT,));self.arm(g,JUDGMENT);attacker=self.entity(g,UNIT,2,'board').id;self.attack(g)
        e=g.state.entities[attacker];self.assertEqual((e.attack,e.max_health,e.damage),(1,1,0));self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,29);self.portable(g)

    def test_judgment_ignores_hero_attack(self):
        g=self.game((JUDGMENT,),other_weapon=WEAPON);self.arm(g,JUDGMENT)
        g.apply(Attack(2,g.state.players[2].hero_id,g.state.players[1].hero_id));self.assertIn(JUDGMENT,self.secrets(g))

    def test_real_reveal_waits_restore_every_original_event_family(self):
        for cid in native.LEAVES:
            with self.subTest(card=cid):
                board=(WATCH,UNIT) if cid in (CAGE,AVENGE,BAIT) else (WATCH,)
                hand=(cid,FILL) if cid==CACHE else (cid,)
                g=self.game(hand,board=board,enemy=(UNIT,),other_hand=(NOOP,NOOP,NOOP,BOLT,KILL,HURT),deck=(FILL,NOOP,WEAPON),mode='reveal');self.arm(g,cid)
                if cid==CAGE:g.apply(EndTurn(2))
                elif cid==AVENGE:self.play(g,KILL,self.entity(g,UNIT,1,'board').id,player=2)
                elif cid==EVADE:self.play(g,HURT,g.state.players[1].hero_id,player=2)
                elif cid in (CACHE,RECKON):self.play(g,BOLT,player=2)
                elif cid==MOTION:
                    for _ in range(3):self.play(g,NOOP,player=2)
                elif cid==BIN:self.play(g,NOOP,player=2)
                else:self.attack(g,target=self.entity(g,UNIT,1,'board').id if cid==BAIT else None)
                self.assertIsNotNone(g.state.pending_choice);self.portable_wait(g)

    def test_bin_original_two_draw_slots_resume_after_actual_first_arrival(self):
        g=self.game((BIN,),board=(WATCH,),deck=(FILL,NOOP,WEAPON),other_hand=(NOOP,),mode='draw');self.arm(g,BIN);self.play(g,NOOP,player=2)
        self.assertIsNotNone(g.state.pending_choice);self.portable_wait(g);self.assertEqual(len(g.state.players[1].hand),2)

    def test_cages_actual_summon_wait_preserves_rng_and_original_material(self):
        g=self.game((CAGE,),board=(WATCH,UNIT),mode='summon');self.arm(g,CAGE);g.apply(EndTurn(2))
        self.assertIsNotNone(g.state.pending_choice);self.portable_wait(g)

    def test_second_actor_owns_private_hand_reward_and_original_hero_immunity(self):
        g=self.game((CACHE,FILL),other_hand=(UNIT,),player=2);self.arm(g,CACHE,2);self.play(g,UNIT,player=1)
        self.assertEqual((self.entity(g,FILL,2).attack,self.entity(g,FILL,2).max_health),(2,10));self.portable(g)
        g=self.game((EVADE,),other_hand=(HURT,),player=2);self.arm(g,EVADE,2);self.play(g,HURT,g.state.players[2].hero_id,player=1)
        self.assertIn(Keyword.IMMUNE,g.state.entities[g.state.players[2].hero_id].keywords);self.portable(g)

    def test_changed_companion_is_rejected_before_partial_batch_registration(self):
        r=opening_registry();register_fixed_companion_cards(r);cid=native.EXISTING[0]
        r._cards[cid]=replace(r.card(cid),attack=99);keys=set(r.cards);behaviors=set(r._behaviors)
        with self.assertRaises(TargetValidationError):native.register_past_secret_event_effects(r)
        self.assertEqual(set(r.cards),keys);self.assertEqual(set(r._behaviors),behaviors)

    def test_complete_host_executes_original_paid_attack_secret_and_keeps_won_closed(self):
        r=host();self.assertNotIn('WON_040',r.cards)
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(JUDGMENT,),mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=('CS2_120',),deck=('CS2_120',))),seed=107),r)
        self.play(g,JUDGMENT);g.apply(EndTurn(1));eid=g.state.players[2].board[0];g.apply(Attack(2,eid,g.state.players[1].hero_id))
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].max_health),(1,1))
        saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,build_cn37_local_pool_format().registry).snapshot(),saved)


if __name__=='__main__':unittest.main()
