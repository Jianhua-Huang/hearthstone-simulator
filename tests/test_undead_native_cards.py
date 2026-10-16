"""Native Undead entry conditions and actual health/turn/summon boundaries."""
from dataclasses import asdict,replace
import json,unittest
from pathlib import Path
from hs_sim.cards import build_registry
from hs_sim.cards.undead_native_cards import(ASCENDANT,TOWER,SPECTER,LIFERENDER,SPIRIT,GHOUL,BATCH_HASH,load_batch)
from hs_sim.engine import(Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,
    Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.effects import(Buff,ChangeControl,ChoiceOption,Damage,DamageBatch,Destroy,ForceAttack,
    GainArmor,Heal,InvokeBehavior,RandomBuff,RequestChoice,Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.hero_health_targets import HeroHealthChangedTargetProfile,changed_this_turn
from hs_sim.engine.model import DamageKind,HealthFlow,HealthOp,HealthRule
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1];YETI='CORE_CS2_182';META=CardMetadata(False,(CardClass.NEUTRAL,),None)


def registry():
    r=build_registry()
    def hero(c,p=None):return c.state.players[c.player_id if p is None else p].hero_id
    def fail(c):raise ResolutionError('K76 deliberate late failure')
    r.register_behavior('k76.fail',fail)
    def wait(c):
        result=health_result(c.event)
        if result is None or result.original_flow!=HealthFlow.HEALING.value or result.source_card_id!=SPIRIT:return()
        return(RequestChoice(c.player_id,(ChoiceOption('keep','Continue',()),ChoiceOption('fail','Fail',
            (InvokeBehavior('k76.fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior('k76.wait',wait)
    r.register_card(CardDefinition('k76.wait','Actual health notification suspension fixture',CardType.MINION,health=9,
        triggers=(TriggerSpec('health_resolved','k76.wait'),),metadata=META))
    r.register_card(CardDefinition('k76.shield','Shield control',CardType.MINION,health=4,keywords=(Keyword.DIVINE_SHIELD,),metadata=META))
    r.register_card(CardDefinition('k76.spellpower','Spell power control',CardType.MINION,health=5,spell_damage=5,metadata=META))
    r.register_card(CardDefinition('k76.heal_double','Actual EFFECT healing modifier fixture',CardType.MINION,health=5,
        health_rules=(HealthRule(HealthFlow.HEALING,HealthOp.SCALE,2,source_relation='friendly'),),metadata=META))
    scripts={
        'ping':lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.EFFECT),),
        'lethal':lambda c:(Damage(c.target_id,9,c.source_id,DamageKind.EFFECT),),
        'zero':lambda c:(Damage(c.target_id,0,c.source_id,DamageKind.EFFECT),),
        'hurt':lambda c:(Damage(hero(c),2,c.source_id,DamageKind.EFFECT),),
        'enemy_hurt':lambda c:(Damage(hero(c,3-c.player_id),2,c.source_id,DamageKind.EFFECT),),
        'heal':lambda c:(Heal(hero(c),3,c.source_id),),
        'net_zero':lambda c:(Damage(hero(c),2,c.source_id),Heal(hero(c),2,c.source_id)),
        'armor':lambda c:(GainArmor(c.player_id,5),),
        'armor_hit':lambda c:(Damage(hero(c),1,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'force':lambda c:(ForceAttack(c.state.players[c.player_id].board[0],hero(c,3-c.player_id)),),
        'control':lambda c:(ChangeControl(c.target_id,c.player_id),),
        'indirect':lambda c:(TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]),c.source_id),),
        'random':lambda c:(RandomBuff(tuple(c.state.players[c.player_id].board),1,1,c.source_id),),
        'roll_back':lambda c:(RandomBuff(tuple(c.state.players[c.player_id].board),1,1,c.source_id),InvokeBehavior('k76.fail',c.source_id,c.player_id)),
    }
    targeted={'ping','lethal','zero','silence','kill','control','indirect'}
    for name,body in scripts.items():
        r.register_behavior('k76.'+name,body)
        r.register_card(CardDefinition('k76.'+name,name,CardType.SPELL,on_play='k76.'+name,metadata=META,
            targeting=TargetSpec()if name in targeted else None))
    return r


class UndeadNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),enemy_hand=()):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=1076),self.r)
    def entities(self,g,cid,p=1,zone='board'):
        s=g.state;return[s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid]
    def first(self,g,cid,p=1,zone='board'):return self.entities(g,cid,p,zone)[0]
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def play(self,g,cid,target=None,p=1):
        eid=self.first(g,cid,p,'hand').id;g.apply(PlayCard(p,eid,target));return eid
    def portable(self,g):
        saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,registry()).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
    def actions(self,g,cid):
        view=g.for_player(1).legal_actions();ref=next(x['ref']for x in view['observation']['players'][0]['hand']if x['card_id']==cid)
        return view,[x for x in view['actions']if x['type']=='play_card'and x['card']==ref]
    def damage(self,g,cid='k76.ping',target=None):return self.play(g,cid,target)
    def random_events(self,g):return[e for e in g.events if e.kind=='random_choice']

    def test_complete_raw_pin_fixed_ghoul_and_dual_specter_tribes(self):
        data=load_batch();self.assertEqual(canonical_digest(data),BATCH_HASH);self.assertEqual(len(data['cards']),5)
        for row in data['cards']+data['existing_dependencies']+data['evidence_only']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(set(self.r.card(SPECTER).metadata.tribes),{'undead','draenei'})
        self.assertEqual(self.r.card(ASCENDANT).metadata.deck_identity,'ICC_210')
        ghoul=self.r.card(GHOUL);self.assertEqual((ghoul.attack,ghoul.health),(1,1));self.assertIn(Keyword.CHARGE,ghoul.keywords)
        self.assertEqual(canonical_digest(asdict(ghoul)),data['existing_dependencies'][0]['definition_sha256'])
    def test_old1037_definitions_and_unused_default_fingerprint_unchanged(self):
        old=json.loads((ROOT/'outputs/card-integration-20261014/k76-before/definition-digests.json').read_bytes())
        self.assertEqual(len(old),1037);self.assertEqual(old,{cid:canonical_digest(asdict(self.r.card(cid)))for cid in old})
        self.assertEqual(representative().fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')
    def test_native_profile_validation_read_only_and_fingerprint(self):
        r=build_registry();p=r.hero_health_target_profiles[LIFERENDER];self.assertEqual(p,HeroHealthChangedTargetProfile(LIFERENDER))
        with self.assertRaises(TypeError):r.hero_health_target_profiles['fake']=p
        with self.assertRaises(ValueError):r.register_hero_health_target_profile(p)
        with self.assertRaises(ValueError):r.register_hero_health_target_profile(HeroHealthChangedTargetProfile(YETI))
        r.freeze()
        with self.assertRaises(ValueError):r.register_hero_health_target_profile(p)
    def test_liferender_unchanged_hero_is_targetless_in_player_commands(self):
        g=self.game((LIFERENDER,),enemy=(YETI,));view,actions=self.actions(g,LIFERENDER)
        self.assertEqual(len(actions),1);self.assertIsNone(actions[0]['target'])
        reply=g.for_player(1).submit(dict(revision=view['revision'],action=actions[0]));self.assertTrue(reply['accepted'])
        self.assertEqual(self.first(g,YETI,2).health,5);self.portable(g)
    def test_liferender_actual_damage_requires_enemy_target_in_player_commands(self):
        g=self.game(('k76.hurt',LIFERENDER),board=(YETI,),enemy=(YETI,));self.play(g,'k76.hurt')
        view,actions=self.actions(g,LIFERENDER);enemy_ref=view['observation']['players'][1]['board'][0]['ref']
        self.assertEqual({a['target']for a in actions},{enemy_ref});self.assertEqual({a['position']for a in actions},{0,1})
        self.assertTrue(changed_this_turn(g.state,1))
        self.assertTrue(g.for_player(1).submit(dict(revision=view['revision'],action=actions[0]))['accepted'])
        self.assertFalse(self.entities(g,YETI,2));self.assertEqual(self.first(g,YETI).health,5);self.portable(g)
    def test_liferender_armor_and_full_overheal_do_not_create_health_change(self):
        for steps in(('k76.armor',),('k76.heal',),('k76.armor','k76.armor_hit')):
            g=self.game((*steps,LIFERENDER),enemy=(YETI,))
            for step in steps:self.play(g,step)
            self.assertFalse(changed_this_turn(g.state,1));self.play(g,LIFERENDER);self.assertEqual(self.first(g,YETI,2).health,5)
    def test_liferender_net_zero_health_still_counts_but_enemy_health_does_not(self):
        for step,active in(('k76.net_zero',True),('k76.enemy_hurt',False)):
            g=self.game((step,LIFERENDER),enemy=(YETI,));self.play(g,step);self.assertEqual(self.hero(g).health,30)
            self.assertEqual(changed_this_turn(g.state,1),active)
            self.play(g,LIFERENDER,self.first(g,YETI,2).id if active else None)
            self.assertEqual(bool(self.entities(g,YETI,2)),not active)
    def test_liferender_previous_turn_does_not_keep_condition(self):
        g=self.game(('k76.hurt',LIFERENDER),enemy=(YETI,));self.play(g,'k76.hurt');g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertFalse(changed_this_turn(g.state,1));self.play(g,LIFERENDER);self.assertEqual(self.first(g,YETI,2).health,5);self.portable(g)
    def test_liferender_active_condition_with_no_enemy_minion_is_still_playable(self):
        g=self.game(('k76.hurt',LIFERENDER));self.play(g,'k76.hurt');self.play(g,LIFERENDER)
        self.assertEqual(self.first(g,LIFERENDER).health,4)
    def test_liferender_opponent_turn_indirect_body_uses_current_global_turn(self):
        g=self.game(board=(LIFERENDER,),enemy=(YETI,),enemy_hand=('k76.enemy_hurt','k76.indirect'))
        g.apply(EndTurn(1));self.play(g,'k76.enemy_hurt',p=2)
        self.assertTrue(changed_this_turn(g.state,1));self.assertFalse(changed_this_turn(g.state,2))
        self.play(g,'k76.indirect',self.first(g,LIFERENDER).id,p=2)
        self.assertFalse(self.entities(g,YETI,2));self.portable(g)
    def test_liferender_rejects_prescribed_inactive_friendly_and_hero_targets(self):
        g=self.game(('k76.hurt',LIFERENDER),board=(YETI,),enemy=(YETI,));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,LIFERENDER,self.first(g,YETI,2).id)
        self.assertEqual(g.snapshot(),before);self.play(g,'k76.hurt')
        for target in(self.first(g,YETI).id,self.hero(g,2).id,None):
            before=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,LIFERENDER,target)
            self.assertEqual(g.snapshot(),before)
    def test_ascendant_buffs_exactly_one_other_friendly_and_both_stats(self):
        g=self.game(board=(ASCENDANT,YETI),enemy=(YETI,));g.apply(EndTurn(1))
        target=self.first(g,YETI);self.assertEqual((target.attack,target.health,target.max_health),(5,6,6))
        self.assertEqual((self.first(g,ASCENDANT).attack,self.first(g,ASCENDANT).health),(2,3))
        self.assertEqual(self.first(g,YETI,2).health,5);self.assertEqual(len(self.random_events(g)),1);self.portable(g)
    def test_ascendant_empty_pool_does_not_consume_rng(self):
        g=self.game(board=(ASCENDANT,));before=g.snapshot()['rng_state'];g.apply(EndTurn(1))
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertFalse(self.random_events(g))
    def test_ascendant_silence_and_opponent_end_do_not_add_trigger(self):
        g=self.game(('k76.silence',),board=(ASCENDANT,YETI));self.play(g,'k76.silence',self.first(g,ASCENDANT).id)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(self.first(g,YETI).health,5);self.assertFalse(self.random_events(g))
    def test_tower_positive_damage_summons_two_native_charge_ghouls(self):
        g=self.game(('k76.ping',),board=(TOWER,));self.play(g,'k76.ping',self.first(g,TOWER).id)
        children=self.entities(g,GHOUL);self.assertEqual(len(children),2)
        self.assertTrue(all((e.attack,e.health)==(1,1)and Keyword.CHARGE in e.keywords for e in children))
        self.portable(g);g.apply(EndTurn(1));self.assertFalse(self.entities(g,GHOUL))
    def test_tower_lethal_takes_damage_does_not_require_surviving(self):
        g=self.game(('k76.lethal',),board=(TOWER,));self.play(g,'k76.lethal',self.first(g,TOWER).id)
        self.assertFalse(self.entities(g,TOWER));self.assertEqual(len(self.entities(g,GHOUL)),2);self.portable(g)
    def test_tower_zero_or_shield_prevention_does_not_trigger(self):
        g=self.game(('k76.zero',),board=(TOWER,));self.play(g,'k76.zero',self.first(g,TOWER).id);self.assertFalse(self.entities(g,GHOUL))
        r=registry();r.register_behavior('k76.shield_tower',lambda c:())
        # The actual source gains a normal shield through an ordinary effect.
        from hs_sim.engine.effects import GrantKeyword
        r.register_behavior('k76.grant_shield',lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),))
        r.register_card(CardDefinition('k76.grant_shield','Shield fixture',CardType.SPELL,targeting=TargetSpec(),on_play='k76.grant_shield',metadata=META))
        scenario=Scenario((PlayerSetup('HERO_08',hand=('k76.grant_shield','k76.ping'),board=(TOWER,),mana=10,max_mana=10),PlayerSetup('HERO_08')))
        h=Game.from_scenario(scenario,r);target=self.first(h,TOWER).id;self.play(h,'k76.grant_shield',target);self.play(h,'k76.ping',target)
        self.assertFalse(self.entities(h,GHOUL));self.assertEqual(self.first(h,TOWER).health,7)
    def test_tower_uses_actual_board_capacity_and_silence_lifecycle(self):
        g=self.game(('k76.ping',),board=(TOWER,)+(YETI,)*5);self.play(g,'k76.ping',self.first(g,TOWER).id)
        self.assertEqual(len(self.entities(g,GHOUL)),1);self.assertEqual(len(g.state.players[1].board),7)
        h=self.game(('k76.silence','k76.ping'),board=(TOWER,));target=self.first(h,TOWER).id
        self.play(h,'k76.silence',target);self.play(h,'k76.ping',target);self.assertFalse(self.entities(h,GHOUL))
    def test_specter_cannot_attack_but_keeps_native_taunt(self):
        g=self.game(board=(SPECTER,),enemy=(YETI,));source=self.first(g,SPECTER)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,source.id,self.hero(g,2).id))
        self.assertIn(Keyword.TAUNT,source.keywords);g.apply(EndTurn(1))
        with self.assertRaises(IllegalAction):g.apply(Attack(2,self.first(g,YETI,2).id,self.hero(g).id))
        self.portable(g)
    def test_specter_silence_removes_restriction_and_taunt(self):
        g=self.game(('k76.silence',),board=(SPECTER,));source=self.first(g,SPECTER).id
        self.play(g,'k76.silence',source);g.apply(Attack(1,source,self.hero(g,2).id))
        self.assertEqual(self.hero(g,2).health,28);self.assertNotIn(Keyword.TAUNT,g.state.entities[source].keywords)
    def test_specter_forced_attack_uses_existing_voluntary_restriction_policy(self):
        g=self.game(('k76.force',),board=(SPECTER,));self.play(g,'k76.force');self.assertEqual(self.hero(g,2).health,28)
        self.portable(g)
    def test_spirit_full_health_excess_damage_and_reborn_are_native(self):
        g=self.game(('k76.kill',),board=(SPIRIT,));old=self.first(g,SPIRIT).id;self.play(g,'k76.kill',old)
        reborn=self.first(g,SPIRIT);self.assertNotEqual(reborn.id,old);self.assertEqual(reborn.health,1)
        self.assertNotIn(Keyword.REBORN,reborn.keywords);self.assertEqual(self.hero(g,2).health,27);self.assertEqual(self.hero(g).health,30);self.portable(g)
    def test_spirit_partial_and_no_excess_use_actual_result(self):
        for hurts,excess in((1,1),(2,0)):
            g=self.game(('k76.hurt',)*hurts+('k76.kill',),board=(SPIRIT,))
            for _ in range(hurts):self.play(g,'k76.hurt')
            before=g.snapshot()['rng_state'];self.play(g,'k76.kill',self.first(g,SPIRIT).id)
            self.assertEqual(self.hero(g,2).health,30-excess)
            if excess==0:self.assertEqual(g.snapshot()['rng_state'],before)
            self.assertEqual(self.hero(g).health,min(30,30-2*hurts+3))
    def test_spirit_healing_conversion_produces_no_invented_excess(self):
        g=self.game(('k76.kill',),board=('EX1_591',SPIRIT));self.play(g,'k76.kill',self.first(g,SPIRIT).id)
        self.assertEqual(self.hero(g).health,27);self.assertEqual(self.hero(g,2).health,30);self.assertFalse(self.random_events(g));self.portable(g)
    def test_spirit_modifier_and_spell_damage_use_original_numeric_types(self):
        g=self.game(('k76.kill',),board=('k76.heal_double',SPIRIT));self.play(g,'k76.kill',self.first(g,SPIRIT).id)
        self.assertEqual(self.hero(g,2).health,24)
        v=self.game(('k76.kill',),board=('EX1_350',SPIRIT));self.play(v,'k76.kill',self.first(v,SPIRIT).id)
        self.assertEqual(self.hero(v,2).health,27)
        h=self.game(('k76.kill',),board=('k76.spellpower',SPIRIT));self.play(h,'k76.kill',self.first(h,SPIRIT).id)
        self.assertEqual(self.hero(h,2).health,27)
    def test_spirit_current_controller_receives_healing_and_selects_its_enemy(self):
        g=self.game(board=(SPIRIT,),enemy_hand=('k76.control','k76.kill'));g.apply(EndTurn(1));source=self.first(g,SPIRIT).id
        self.play(g,'k76.control',source,p=2);self.play(g,'k76.kill',source,p=2)
        self.assertEqual(self.hero(g).health,27);self.assertEqual(self.hero(g,2).health,30);self.assertTrue(self.entities(g,SPIRIT,2));self.portable(g)
    def test_spirit_real_notification_waiting_restores_and_rolls_back_failed_resume(self):
        g=self.game(('k76.kill',),board=('k76.wait',SPIRIT));self.play(g,'k76.kill',self.first(g,SPIRIT).id)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);saved=g.snapshot();q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(q.player_id,q.id,('fail',)))
        self.assertEqual(g.snapshot(),saved);g.apply(SelectChoice(q.player_id,q.id,('keep',)))
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.hero(g,2).health,27);self.portable(g)
    def test_random_buff_validation_and_late_failure_restore_rng_and_stats(self):
        for value in((1,1),(True,),[1]):
            with self.assertRaises(ValueError):RandomBuff(value,1,1)
        g=self.game(('k76.roll_back',),board=(YETI,YETI));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k76.roll_back')
        self.assertEqual(g.snapshot(),before)
    def test_old_schema_is_rejected_and_private_health_history_is_not_projected(self):
        old=json.loads((ROOT/'outputs/card-integration-20261014/k76-before/constructed-v84-core369-schema294.json').read_bytes())
        with self.assertRaises(SnapshotError):Game.from_snapshot(old,build_registry())
        g=self.game(('k76.hurt',LIFERENDER));self.play(g,'k76.hurt')
        for p in(1,2):
            view=json.dumps(g.observe(p),sort_keys=True)
            for field in('hero_health_change_history','hero_health_transition','rng_state','original_state_hash'):
                self.assertNotIn(field,view)


if __name__=='__main__':unittest.main()
