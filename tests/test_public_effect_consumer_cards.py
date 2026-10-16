"""Nine real cards reusing public rules, plus the actual enemy-Taunt aura domain."""
from dataclasses import asdict,fields,replace
import json,unittest
from pathlib import Path
from hs_sim.cards import build_registry
from hs_sim.cards.public_effect_consumer_cards import (GEOMANCER,LANCER,AMARA,STAFF,DOUBLE,ARACHNATHID,SUPPLIER,GALVADON,CAUSALITY,ROOTS,BATCH_HASH,load_batch)
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,Keyword,
    KeywordAuraSpec,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,UseHandAction,Zone)
from hs_sim.engine.bonus_effects import BONUS_EFFECTS
from hs_sim.engine.effects import (Buff,ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,Draw,GainArmor,
    InvokeBehavior,RequestChoice,ReturnToHand,Silence,SetStats)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_loss import ChangeHeroMaxHealth
from hs_sim.engine.model import CostSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.engine.zones import CardReference,ModifyStoredCost
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1];YETI='CORE_CS2_182';FIREBALL='CORE_CS2_029';BOLT='CORE_CS2_024';REPLACEMENT='EDR_253';DORMANT='EDR_979'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


def registry():
    r=build_registry();r.register_behavior('k80.noop',lambda c:())
    def fail(c):raise ResolutionError('K80 deliberate choice failure')
    r.register_behavior('k80.fail',fail)
    for cid,attack,health,keywords in(('fodder',1,1,()),('wall',1,30,()),('taunt',1,3,(Keyword.TAUNT,)),
        ('nearly_full',1,9,tuple(k for k in BONUS_EFFECTS if k!=Keyword.ELUSIVE))):
        r.register_card(CardDefinition('k80.'+cid,cid,CardType.MINION,attack=attack,health=health,keywords=keywords,metadata=META))
    r.register_card(CardDefinition('k80.location','Location is not a minion',CardType.LOCATION,durability=2,on_use='k80.noop',metadata=META))
    def wait(c):return (RequestChoice(c.player_id,(ChoiceOption('keep','Continue',()),ChoiceOption('fail','Fail',(InvokeBehavior('k80.fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior('k80.dr_wait',wait);r.register_card(CardDefinition('k80.dr_wait','Death waiting source',CardType.MINION,health=1,deathrattle='k80.dr_wait',metadata=META))
    def entry(c):
        row=c.state.play_history[-1]if c.state.play_history else None
        if row is None or row.card_id!=DOUBLE or row.source_id!=c.event.target_id:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('keep','Continue',()),ChoiceOption('buff','Grow original',
            (Buff(row.source_id,2,1,source_id=c.source_id),)),ChoiceOption('fail','Fail',(InvokeBehavior('k80.fail',c.source_id,c.player_id),))),c.source_id),)
    def draw_wait(c):
        if c.draw is None or c.draw.source_id is None or c.state.entities[c.draw.source_id].card_id!=SUPPLIER or c.draw.player_id!=c.player_id:return ()
        return wait(c)
    def health_wait(c):
        if c.event.source_id is None or c.state.entities[c.event.source_id].card_id!=AMARA:return ()
        return wait(c)
    def cancel(c):
        return (ReturnToHand(c.event.source_id),)if c.event.player_id!=c.player_id and c.state.entities[c.event.source_id].card_id==SUPPLIER else ()
    for name,event,body in(('entry_wait','minion_summoned',entry),('draw_wait','card_drawn',draw_wait),('health_wait','stats_changed',health_wait),('cancel','attack_declared',cancel)):
        r.register_behavior('k80.'+name,body);r.register_card(CardDefinition('k80.'+name,name,CardType.MINION,health=20,triggers=(TriggerSpec(event,'k80.'+name),),metadata=META))
    def mark_deck(c):
        return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(delta=-1),c.source_id)for i in c.state.players[c.player_id].deck)
    scripts={
        'silence':lambda c:(Silence(c.target_id),),'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'control':lambda c:(ChangeControl(c.target_id,c.player_id),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'armor':lambda c:(GainArmor(c.player_id,6),),
        'damage_owner':lambda c:(Damage(c.state.players[c.player_id].hero_id,9,c.source_id),),
        'grow_max':lambda c:(ChangeHeroMaxHealth(c.player_id,20,c.source_id),),
        'lower_max':lambda c:(ChangeHeroMaxHealth(c.player_id,-10,c.source_id),),
        'break_weapon':lambda c:(Destroy(c.state.players[c.player_id].weapon_id,c.source_id),),
        'mark_deck':mark_deck,'noop':lambda c:(),
    }
    for name,body in scripts.items():
        key='k80.script_'+name;r.register_behavior(key,body)
        r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name in('silence','kill','control','copy')else None,metadata=META))
    return r


class PublicEffectConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=(YETI,)*10,mana=40,seed=1080):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=mana,max_mana=mana,mana_cap=40,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*10,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=seed),self.r)
    def entities(self,g,cid,p=1,zone='board'):
        s=g.state;return[s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid]
    def first(self,g,cid,p=1,zone='board'):return self.entities(g,cid,p,zone)[0]
    def play(self,g,cid,target=None,p=1):
        eid=self.first(g,cid,p,'hand').id;g.apply(PlayCard(p,eid,target));return eid
    def script(self,g,name,target=None,p=1):return self.play(g,'k80.script_'+name,target,p)
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def choose(self,g,key):q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,registry()).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]

    def test_complete_nine_faces_three_enchantments_and_no_missing_children(self):
        data=load_batch();self.assertEqual(canonical_digest(data),BATCH_HASH);self.assertEqual((len(data['cards']),len(data['dependencies']),len(data['evidence_only'])),(9,0,3))
        for row in data['cards']+data['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual((self.r.card(STAFF).kind,self.r.card(STAFF).attack,self.r.card(STAFF).health,self.r.card(STAFF).durability),(CardType.WEAPON,1,0,6))
        self.assertIsNone(self.r.card(DOUBLE).battlecry);self.assertIn(Keyword.COMBO,self.r.card(DOUBLE).keywords)
    def test_old1059_complete_definitions_and_unused_default_fingerprint_preserved(self):
        old=json.loads((ROOT/'outputs/card-integration-20261014/k80-before/definition-digests.json').read_bytes())
        self.assertEqual(len(old),1059);self.assertEqual(old,{cid:canonical_digest(asdict(self.r.card(cid)))for cid in old})
        self.assertEqual(representative().fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')
    def test_enemy_aura_domain_is_the_actual_native_taunt_scope(self):
        self.assertEqual(self.r.card(LANCER).keyword_auras,(KeywordAuraSpec(Keyword.TAUNT,'enemy_minions'),))
        for values in({'keyword':Keyword.POISONOUS},{'include_self':True},{'adjacent_only':True},{'condition':'controller_turn'}):
            with self.subTest(values=values),self.assertRaises(ValueError):KeywordAuraSpec(**dict(keyword=values.get('keyword',Keyword.TAUNT),target='enemy_minions',**{k:v for k,v in values.items()if k!='keyword'}))
    def test_geomancer_prepare_uses_native_investment_and_next_turn_zero_cost(self):
        g=self.game((GEOMANCER,));source=self.first(g,GEOMANCER,zone='hand').id;g.apply(UseHandAction(1,source,'prepare'))
        self.assertEqual((g.state.players[1].mana,g.quote_cost(source).amount),(38,0))
        with self.assertRaises(IllegalAction):g.apply(PlayCard(1,source))
        self.cycle(g);self.play(g,GEOMANCER);self.assertEqual(g.state.players[1].mana,40);self.portable(g)
    def test_geomancer_spell_damage_only_from_live_board_provider(self):
        g=self.game((GEOMANCER,FIREBALL));self.play(g,FIREBALL,g.state.players[2].hero_id);self.assertEqual(self.hero(g,2).health,24)
        h=self.game((GEOMANCER,FIREBALL));self.play(h,GEOMANCER);self.play(h,FIREBALL,h.state.players[2].hero_id);self.assertEqual(self.hero(h,2).health,23)
    def test_geomancer_silence_removes_spell_bonus(self):
        g=self.game((GEOMANCER,FIREBALL,'k80.script_silence'));source=self.play(g,GEOMANCER);self.script(g,'silence',source)
        self.play(g,FIREBALL,g.state.players[2].hero_id);self.assertEqual(self.hero(g,2).health,24)
    def test_lancer_grants_only_enemy_minion_taunt_and_blocks_hero_attack(self):
        g=self.game((LANCER,),board=(YETI,),enemy=('k80.fodder',));self.play(g,LANCER);own=self.first(g,YETI).id;enemy=self.first(g,'k80.fodder',2)
        self.assertIn(Keyword.TAUNT,enemy.keywords);self.assertNotIn(Keyword.TAUNT,self.first(g,YETI).keywords)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,own,g.state.players[2].hero_id))
        g.apply(Attack(1,own,enemy.id));self.assertEqual(g.state.entities[enemy.id].zone,Zone.GRAVEYARD);self.portable(g)
    def test_lancer_dormant_and_location_occupants_do_not_receive_taunt(self):
        g=self.game((LANCER,),enemy=(DORMANT,'k80.location','k80.fodder'));self.play(g,LANCER)
        self.assertNotIn(Keyword.TAUNT,self.first(g,DORMANT,2).keywords);self.assertNotIn(Keyword.TAUNT,self.first(g,'k80.location',2).keywords)
    def test_lancer_silence_removes_only_its_aura_contribution(self):
        g=self.game(('k80.script_silence',),board=(LANCER,),enemy=('k80.fodder','k80.taunt'));self.script(g,'silence',self.first(g,LANCER).id)
        self.assertNotIn(Keyword.TAUNT,self.first(g,'k80.fodder',2).keywords);self.assertIn(Keyword.TAUNT,self.first(g,'k80.taunt',2).keywords)
    def test_lancer_control_change_uses_current_enemies(self):
        g=self.game(('k80.script_control',),board=(YETI,),enemy=(LANCER,'k80.fodder'));source=self.first(g,LANCER,2).id
        self.assertIn(Keyword.TAUNT,self.first(g,YETI).keywords);self.script(g,'control',source)
        self.assertNotIn(Keyword.TAUNT,self.first(g,YETI).keywords);self.assertIn(Keyword.TAUNT,self.first(g,'k80.fodder',2).keywords);self.portable(g)
    def test_lancer_current_copy_keeps_aura_until_last_source_leaves(self):
        g=self.game(('k80.script_copy','k80.script_kill'),board=(LANCER,),enemy=('k80.fodder',));source=self.first(g,LANCER).id
        self.script(g,'copy',source);self.script(g,'kill',source);self.assertIn(Keyword.TAUNT,self.first(g,'k80.fodder',2).keywords)
        self.assertEqual(len(self.entities(g,LANCER)),1)
    def test_arachnathid_includes_self_and_friendlies_but_not_enemies(self):
        g=self.game((ARACHNATHID,),board=(YETI,),enemy=('k80.wall',));source=self.play(g,ARACHNATHID)
        self.assertIn(Keyword.POISONOUS,self.first(g,YETI).keywords);self.assertIn(Keyword.POISONOUS,g.state.entities[source].keywords)
        self.assertNotIn(Keyword.POISONOUS,self.first(g,'k80.wall',2).keywords)
        g.apply(Attack(1,source,self.first(g,'k80.wall',2).id));self.assertFalse(self.entities(g,'k80.wall',2));self.portable(g)
    def test_arachnathid_removal_drops_continuous_poisonous(self):
        g=self.game(('k80.script_kill',),board=(ARACHNATHID,YETI));self.script(g,'kill',self.first(g,ARACHNATHID).id)
        self.assertNotIn(Keyword.POISONOUS,self.first(g,YETI).keywords)
    def test_amara_sets_current_and_maximum_to40_not_clamped_old30(self):
        g=self.game((AMARA,'k80.script_damage_owner','k80.script_armor'));self.script(g,'damage_owner');self.script(g,'armor');source=self.hero(g).id
        before_heal=sum(e.kind=='healed'for e in g.events);self.play(g,AMARA)
        self.assertEqual((self.hero(g).id,self.hero(g).health,self.hero(g).max_health,self.hero(g).armor),(source,40,40,6))
        self.assertEqual(sum(e.kind=='healed'for e in g.events),before_heal);self.assertEqual(g.state.players[1].mana,30);self.portable(g)
    def test_amara_ordered_assignment_replaces_smaller_maximum(self):
        g=self.game((AMARA,'k80.script_lower_max'));self.script(g,'lower_max');self.assertEqual(self.hero(g).max_health,20)
        self.play(g,AMARA);self.assertEqual((self.hero(g).health,self.hero(g).max_health),(40,40))
    def test_amara_uses_existing_set_layer_for_larger_prior_local_maximum(self):
        g=self.game((AMARA,'k80.script_grow_max'));self.script(g,'grow_max');self.assertEqual(self.hero(g).max_health,50)
        self.play(g,AMARA);self.assertEqual((self.hero(g).health,self.hero(g).max_health),(40,40))
    def test_amara_stat_notification_wait_restore_and_choice_failure(self):
        g=self.game((AMARA,),board=('k80.health_wait',));self.play(g,AMARA);self.assertEqual(self.hero(g).health,40);self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'keep');self.assertEqual(self.hero(g).max_health,40)
    def test_staff_equipment_replacement_destroys_both_boards_but_not_heroes(self):
        g=self.game((STAFF,REPLACEMENT),board=(YETI,),enemy=('k80.fodder',));staff=self.play(g,STAFF);self.play(g,REPLACEMENT)
        self.assertFalse(g.state.players[1].board);self.assertFalse(g.state.players[2].board)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(30,30));self.assertEqual(g.state.entities[staff].zone,Zone.GRAVEYARD);self.portable(g)
    def test_staff_is_six_durability_weapon_and_normal_attack_wears_once(self):
        g=self.game((STAFF,));source=self.play(g,STAFF);self.assertEqual(g.state.entities[source].durability,6)
        g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id));self.assertEqual(g.state.entities[source].durability,5)
    def test_staff_deathrattle_skips_dormancy_and_locations(self):
        g=self.game((STAFF,'k80.script_break_weapon'),board=(DORMANT,'k80.location',YETI));self.play(g,STAFF);self.script(g,'break_weapon')
        self.assertTrue(self.entities(g,DORMANT));self.assertTrue(self.entities(g,'k80.location'));self.assertFalse(self.entities(g,YETI))
    def test_staff_shared_death_coordinator_waits_and_restores_original_deaths(self):
        g=self.game((STAFF,'k80.script_break_weapon'),board=('k80.dr_wait',YETI),enemy=('k80.fodder',));self.play(g,STAFF);self.script(g,'break_weapon')
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);before=len(g.state.death_history);self.choose(g,'keep')
        self.assertEqual(len(g.state.death_history),before);self.assertFalse(g.state.players[1].board);self.assertFalse(g.state.players[2].board)
    def test_double_without_prior_card_is_one_paid_stealthed_minion(self):
        g=self.game((DOUBLE,));self.play(g,DOUBLE);self.assertEqual(len(self.entities(g,DOUBLE)),1);self.assertFalse(g.state.combo_history)
        self.assertEqual(g.state.players[1].mana,36)
    def test_double_native_combo_copies_once_without_replaying_payment(self):
        g=self.game((DOUBLE,'k80.script_noop'));self.script(g,'noop');source=self.play(g,DOUBLE)
        self.assertEqual(len(self.entities(g,DOUBLE)),2);self.assertTrue(all(Keyword.STEALTH in e.keywords for e in self.entities(g,DOUBLE)))
        self.assertEqual((len(g.state.combo_history),g.state.players[1].mana),(1,36));self.assertEqual(g.state.combo_history[0].source_id,source);self.portable(g)
    def test_double_full_board_keeps_original_and_does_not_copy_or_refund(self):
        g=self.game((DOUBLE,'k80.script_noop'),board=('k80.fodder',)*6);self.script(g,'noop');self.play(g,DOUBLE)
        self.assertEqual((len(g.state.players[1].board),len(self.entities(g,DOUBLE)),g.state.players[1].mana),(7,1,36))
    def test_double_entry_wait_uses_current_buffed_copy_and_original_combo(self):
        g=self.game((DOUBLE,'k80.script_noop'),board=('k80.entry_wait',));self.script(g,'noop');self.play(g,DOUBLE);self.portable(g);self.choose(g,'buff')
        self.assertEqual([(e.attack,e.max_health)for e in self.entities(g,DOUBLE)],[(5,4),(5,4)]);self.assertEqual(len(g.state.combo_history),1)
    def test_supplier_own_completed_attack_draws_after_damage_and_loses_stealth(self):
        g=self.game(board=(SUPPLIER,));source=self.first(g,SUPPLIER).id;g.apply(Attack(1,source,g.state.players[2].hero_id))
        self.assertEqual((len(g.state.draw_history),self.hero(g,2).health),(1,29));self.assertNotIn(Keyword.STEALTH,g.state.entities[source].keywords);self.portable(g)
    def test_supplier_other_attacker_does_not_draw(self):
        g=self.game(board=(SUPPLIER,YETI));g.apply(Attack(1,self.first(g,YETI).id,g.state.players[2].hero_id));self.assertFalse(g.state.draw_history)
    def test_supplier_cancelled_attack_does_not_draw(self):
        g=self.game(board=(SUPPLIER,),enemy=('k80.cancel',));source=self.first(g,SUPPLIER).id;g.apply(Attack(1,source,g.state.players[2].hero_id))
        self.assertFalse(g.state.draw_history);self.assertEqual(g.state.entities[source].zone,Zone.HAND)
    def test_supplier_existing_living_source_policy_skips_lethal_retaliation(self):
        g=self.game(board=(SUPPLIER,),enemy=(YETI,));g.apply(Attack(1,self.first(g,SUPPLIER).id,self.first(g,YETI,2).id))
        self.assertFalse(g.state.draw_history);self.assertFalse(self.entities(g,SUPPLIER))
    def test_supplier_draw_wait_choice_failure_and_replay(self):
        g=self.game(board=(SUPPLIER,'k80.draw_wait'));g.apply(Attack(1,self.first(g,SUPPLIER).id,g.state.players[2].hero_id));self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'keep');self.assertEqual(len(g.state.draw_history),1)
    def test_galvadon_gives_three_distinct_board_bonus_effects(self):
        g=self.game((GALVADON,),board=(YETI,));target=self.first(g,YETI).id;self.play(g,GALVADON,target)
        keywords=g.state.entities[target].keywords;self.assertEqual(len(keywords),3);self.assertTrue(keywords<=set(BONUS_EFFECTS));self.assertNotIn(Keyword.RUSH,keywords);self.portable(g)
    def test_galvadon_accepts_enemy_minion_and_not_a_hero(self):
        g=self.game((GALVADON,),enemy=(YETI,));source=self.first(g,GALVADON,zone='hand').id
        with self.assertRaises(IllegalAction):g.apply(PlayCard(1,source,g.state.players[1].hero_id))
        self.play(g,GALVADON,self.first(g,YETI,2).id);self.assertEqual(len(self.first(g,YETI,2).keywords),3)
    def test_galvadon_stops_at_complete_current_bonus_pool(self):
        g=self.game((GALVADON,),board=('k80.nearly_full',));target=self.first(g,'k80.nearly_full').id;self.play(g,GALVADON,target)
        self.assertEqual(g.state.entities[target].keywords,set(BONUS_EFFECTS))
    def test_causality_reverses_physical_ids_without_rng_or_zone_reentry(self):
        g=self.game((CAUSALITY,),deck=(YETI,BOLT,FIREBALL));before=g.state;ids=before.players[1].deck;rng=g._rng.getstate();self.play(g,CAUSALITY)
        self.assertEqual(g.state.players[1].deck,list(reversed(ids)));self.assertEqual(g._rng.getstate(),rng)
        self.assertTrue(all(g.state.entities[i].zone_epoch==before.entities[i].zone_epoch for i in ids));self.assertFalse([e for e in g.events if e.kind=='deck_shuffled']);self.portable(g)
    def test_causality_preserves_stored_costs_and_duplicate_faces(self):
        g=self.game((CAUSALITY,'k80.script_mark_deck'),deck=(YETI,YETI,BOLT));self.script(g,'mark_deck');before=g.state;ids=before.players[1].deck
        self.play(g,CAUSALITY);self.assertEqual(g.state.players[1].deck,list(reversed(ids)))
        self.assertTrue(all(g.state.entities[i].enchantments==before.entities[i].enchantments for i in ids))
    def test_causality_two_real_plays_restore_original_order(self):
        g=self.game((CAUSALITY,CAUSALITY),deck=(YETI,BOLT,FIREBALL));before=g.state.players[1].deck
        self.play(g,CAUSALITY);self.play(g,CAUSALITY);self.assertEqual(g.state.players[1].deck,before)
    def test_causality_empty_deck_and_opponent_information_stay_ordinary(self):
        g=self.game((CAUSALITY,),deck=());rng=g._rng.getstate();self.play(g,CAUSALITY);self.assertEqual(g._rng.getstate(),rng)
        h=self.game((CAUSALITY,),deck=(YETI,BOLT,FIREBALL));self.play(h,CAUSALITY);text=json.dumps(h.observe(2))
        self.assertNotIn(BOLT,text);self.assertNotIn(FIREBALL,text)
    def test_old_schema298_default_and_constructed_snapshots_are_rejected(self):
        for name in('constructed-v88','default-v65'):
            with self.subTest(name=name),self.assertRaises(SnapshotError):Game.from_snapshot(json.loads((ROOT/f'outputs/card-integration-20261014/k80-before/{name}-core373-schema298.json').read_bytes()),self.r if name.startswith('constructed')else representative())


if __name__=='__main__':unittest.main()
