"""Actual native Battlecry faces and the original target/resource lifetimes."""
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.simple_battlecry_cards import load_batch
from hs_sim.engine import (Attack,CardDefinition,CardType,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec)
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,Damage,Draw,EquipWeapon,GainArmor,
    InvokeBehavior,RequestChoice,Silence,Summon)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import DamageKind,Zone
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest


def registry(mode=None):
    r=build_registry()
    scripts={
        'hero_attack':lambda c:(Buff(c.state.players[c.player_id].hero_id,attack=4,
            source_id=c.source_id,expires_turn=c.state.turn),),
        'hurt':lambda c:(Damage(c.state.players[c.player_id].hero_id,8,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'summon':lambda c:tuple(Summon(c.player_id,cid) for cid in ('CORE_NEW1_018','CORE_GIL_623','EDR_800')),
        'fail':lambda c:(AddToHand(c.player_id,'missing.k22'),),
    }
    for name,body in scripts.items():
        r.register_behavior('k22.'+name,body)
        if name!='fail':r.register_card(CardDefinition('k22.'+name,name,CardType.SPELL,
            on_play='k22.'+name,requires_target=name=='silence'))
    if mode:
        def watch(c):
            if c.event.player_id!=1:return ()
            if mode in ('raider','grizzly'):
                expected='CORE_NEW1_018' if mode=='raider' else 'CORE_GIL_623'
                if c.state.entities[c.event.source_id].card_id!=expected:return ()
                good=(EquipWeapon(1,'EX1_383t'),) if mode=='raider' else (Draw(2,source_id=c.source_id),)
            else:good=(GainArmor(1,1),)
            return (RequestChoice(1,(
                ChoiceOption('ok','Finish accepted effect',good),
                ChoiceOption('bad','Rollback',(InvokeBehavior('k22.fail',c.source_id,1),))),c.source_id),)
        r.register_behavior('k22.watch',watch)
        event='minion_summoned' if mode in ('raider','grizzly') else 'card_drawn'
        r.register_card(CardDefinition('k22.watch','Observer',CardType.MINION,health=8,
            triggers=(TriggerSpec(event,'k22.watch'),)))
    return r


class SimpleBattlecryCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=registry()
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=('CORE_CS2_182',)*5,
             weapon=None,mode=None,hero='HERO_05'):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=deck,weapon_card_id=weapon,
                mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=('CORE_CS2_182',)*5)),seed=307),
            registry(mode) if mode else self.registry)
    def play(self,g,cid,target=None):
        eid=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid)
        g.apply(PlayCard(1,eid,target));return eid
    def body(self,g,cid,p=1):return next(g.state.entities[e] for e in g.state.players[p].board if g.state.entities[e].card_id==cid)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,mode=None):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(mode))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved);return other
    def rows(self,g,cid):return [r.health_result for r in g.state.damage_history if r.health_result.source_card_id==cid]

    def test_eight_full_faces_hashes_keywords_and_native_entry(self):
        data=load_batch();self.assertEqual(len(data['cards']),8)
        for row in data['cards']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            raw=row['record'];card=self.registry.card(raw['id'])
            self.assertEqual((card.cost,card.attack,card.health),(raw['cost'],raw['attack'],raw['health']))
            self.assertIsNotNone(card.battlecry);self.assertIsNone(card.on_play)
        self.assertEqual(set(self.registry.card('EDR_800').keywords),{Keyword.TAUNT,Keyword.DIVINE_SHIELD})
        self.assertIn(Keyword.LIFESTEAL,self.registry.card('EDR_449').keywords)

    def test_raider_no_weapon_keeps_printed_stats(self):
        g=self.game(('CORE_NEW1_018',));source=self.play(g,'CORE_NEW1_018')
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(2,3))

    def test_raider_uses_weapon_attack_not_extra_hero_attack(self):
        g=self.game(('k22.hero_attack','CORE_NEW1_018'),weapon='EX1_383t')
        self.play(g,'k22.hero_attack');source=self.play(g,'CORE_NEW1_018')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack,9)
        self.assertEqual(g.state.entities[source].attack,7);self.portable(g)

    def test_raider_queries_current_replacement_after_real_summon_choice(self):
        g=self.game(('CORE_NEW1_018',),board=('k22.watch',),weapon='CS2_082',mode='raider')
        source=self.play(g,'CORE_NEW1_018');self.assertIsNotNone(g.state.pending_choice)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g,'raider')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[source].attack,7)

    def test_ghoul_other_minions_one_batch_shield_and_no_spell_bonus(self):
        g=self.game(('CORE_OG_149',),board=('CORE_EX1_012','CORE_CS2_182'),enemy=('CORE_CS2_182','CORE_EX1_008'))
        source=self.play(g,'CORE_OG_149');rows=self.rows(g,'CORE_OG_149')
        self.assertEqual(g.state.entities[source].health,3)
        self.assertEqual((self.body(g,'CORE_CS2_182').health,self.body(g,'CORE_CS2_182',2).health),(4,4))
        self.assertEqual(self.body(g,'CORE_EX1_008',2).health,1)
        self.assertNotIn(Keyword.DIVINE_SHIELD,self.body(g,'CORE_EX1_008',2).keywords)
        self.assertEqual(len(rows),4);self.assertEqual(len({r.batch_id for r in rows}),1)
        self.assertTrue(all(r.modified_amount==1 and r.spell_bonus==0 for r in rows))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)

    def test_ghoul_empty_other_board_does_not_damage_itself_or_heroes(self):
        g=self.game(('CORE_OG_149',));source=self.play(g,'CORE_OG_149')
        self.assertFalse(self.rows(g,'CORE_OG_149'));self.assertEqual(g.state.entities[source].health,3)
        self.assertTrue(all(g.state.entities[p.hero_id].health==30 for p in g.state.players.values()))

    def test_striker_current_hero_attack_no_spell_bonus_or_attack_consumption(self):
        g=self.game(('k22.hero_attack','CORE_TRL_240'),board=('CORE_EX1_012',),enemy=('CORE_CS2_182',))
        self.play(g,'k22.hero_attack');target=self.body(g,'CORE_CS2_182',2).id
        self.play(g,'CORE_TRL_240',target)
        self.assertEqual(g.state.entities[target].health,1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].attacks_this_turn,0)
        self.assertEqual(self.rows(g,'CORE_TRL_240')[0].spell_bonus,0);self.portable(g)

    def test_striker_zero_attack_does_not_invent_damage(self):
        g=self.game(('CORE_TRL_240',),enemy=('CORE_CS2_182',));target=self.body(g,'CORE_CS2_182',2).id
        self.play(g,'CORE_TRL_240',target);self.assertEqual(g.state.entities[target].health,5)
        self.assertTrue(all(r.damage_dealt==0 for r in self.rows(g,'CORE_TRL_240')))

    def test_striker_only_enemy_minion_required_when_available(self):
        g=self.game(('CORE_TRL_240',),board=('CORE_CS2_182',),enemy=('CORE_CS2_182',))
        for target in (None,g.state.players[2].hero_id,self.body(g,'CORE_CS2_182').id):
            before=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,'CORE_TRL_240',target)
            self.assertEqual(g.snapshot(),before)

    def test_striker_playable_with_no_enemy_minion(self):
        g=self.game(('k22.hero_attack','CORE_TRL_240'));self.play(g,'k22.hero_attack')
        self.play(g,'CORE_TRL_240');self.assertFalse(self.rows(g,'CORE_TRL_240'))

    def test_shard_enemy_hero_or_minion_and_rejects_friendly(self):
        for enemy_hero in (True,False):
            g=self.game(('CORE_UNG_205',),board=('CORE_CS2_182',),enemy=('CORE_CS2_182',))
            for target in (g.state.players[1].hero_id,self.body(g,'CORE_CS2_182').id):
                with self.assertRaises(IllegalAction):self.play(g,'CORE_UNG_205',target)
            target=g.state.players[2].hero_id if enemy_hero else self.body(g,'CORE_CS2_182',2).id
            self.play(g,'CORE_UNG_205',target);self.assertTrue(g.state.entities[target].frozen)

    def test_grizzly_loses_health_not_damage_and_silence_restores_face(self):
        g=self.game(('CORE_GIL_623','k22.silence'),enemy_hand=('CORE_CS2_182',)*3)
        source=self.play(g,'CORE_GIL_623');bear=g.state.entities[source]
        self.assertEqual((bear.attack,bear.health,bear.max_health),(3,9,9))
        self.assertFalse(self.rows(g,'CORE_GIL_623'));self.assertIn(Keyword.TAUNT,bear.keywords)
        self.play(g,'k22.silence',source);bear=g.state.entities[source]
        self.assertEqual((bear.health,bear.max_health),(12,12));self.assertNotIn(Keyword.TAUNT,bear.keywords)

    def test_grizzly_zero_and_full_enemy_hand(self):
        for count in (0,10):
            g=self.game(('CORE_GIL_623',),enemy_hand=('CORE_CS2_182',)*count)
            source=self.play(g,'CORE_GIL_623');self.assertEqual(g.state.entities[source].health,12-count)

    def test_grizzly_current_enemy_hand_after_summon_reaction_draw(self):
        g=self.game(('CORE_GIL_623',),board=('k22.watch',),enemy_hand=('CORE_CS2_182',),mode='grizzly')
        source=self.play(g,'CORE_GIL_623');self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g,'grizzly')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[source].health,10)

    def test_hound_draws_physical_beast_then_imbues(self):
        g=self.game(('EDR_226',),deck=('CORE_CS2_182','EDR_227','CORE_CS2_029'))
        before=list(g.state.players[1].deck);self.play(g,'EDR_226')
        self.assertEqual(g.state.players[1].hand,[before[1]])
        self.assertEqual(g.state.players[1].deck,[before[0],before[2]])
        self.assertEqual(len(g.state.imbue_history),1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,'EDR_850p')

    def test_hound_empty_match_or_empty_deck_still_imbues_without_fatigue(self):
        for deck in ((),('CORE_CS2_182',)):
            g=self.game(('EDR_226',),deck=deck);before=g.snapshot()['rng_state'];self.play(g,'EDR_226')
            self.assertEqual(len(g.state.imbue_history),1);self.assertFalse(g.state.draw_history)
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)
            self.assertEqual(g.snapshot()['rng_state'],before)

    def test_hound_draw_choice_before_imbue_bad_rollback_and_portability(self):
        g=self.game(('EDR_226',),deck=('EDR_227',),board=('k22.watch',),mode='draw')
        self.play(g,'EDR_226');self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(g.state.imbue_history);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g,'draw')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.imbue_history),1)

    def test_hound_random_choice_preserves_selected_physical_draw_and_private_deck(self):
        g=self.game(('EDR_226',),deck=('EDR_227','EDR_449'),board=('k22.watch',),mode='draw')
        before=set(g.state.players[1].deck);rng=g.snapshot()['rng_state']
        self.play(g,'EDR_226');self.assertIsNotNone(g.state.pending_choice)
        self.assertNotEqual(g.snapshot()['rng_state'],rng);selected=g.state.draw_history[0].entity_id
        other=self.portable(g,'draw')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.draw_history),1)
        self.assertIn(g.state.draw_history[0].entity_id,before);self.assertEqual(g.state.draw_history[0].entity_id,selected)
        public=json.dumps(g.observe(2));self.assertNotIn('rng_state',public);self.assertNotIn('EDR_227',public)

    def test_all_three_imbue_battlecries_use_actual_current_hunter_class(self):
        g=self.game(('EDR_226','EDR_449','EDR_800'),deck=())
        for cid in ('EDR_226','EDR_449','EDR_800'):self.play(g,cid)
        self.assertEqual(len(g.state.imbue_history),3)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,'EDR_850p');self.portable(g)

    def test_moonwing_lifesteal_uses_real_combat_damage(self):
        g=self.game(('k22.hurt',),board=('EDR_449',),enemy=('CORE_CS2_182',))
        self.play(g,'k22.hurt');source=self.body(g,'EDR_449').id;target=self.body(g,'CORE_CS2_182',2).id
        g.apply(Attack(1,source,target))
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,25)

    def test_summoning_does_not_execute_native_battlecries(self):
        g=self.game(('k22.summon',),enemy_hand=('CORE_CS2_182',)*4,weapon='EX1_383t')
        self.play(g,'k22.summon')
        self.assertEqual(self.body(g,'CORE_NEW1_018').attack,2)
        self.assertEqual(self.body(g,'CORE_GIL_623').health,12)
        self.assertFalse(g.state.imbue_history);self.portable(g)
