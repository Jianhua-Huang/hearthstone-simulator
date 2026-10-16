"""Complete canonical starting roles and default power effects over existing mechanics."""
from dataclasses import replace
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.basic_hero_roles import load_batch,TOTEMS
from hs_sim.cards.metadata import reviewed_definition_digest
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,
    Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,UseHeroPower,Zone)
from hs_sim.engine.construction import DeckPolicy,DeckSpec,MatchSetup
from hs_sim.engine.cross_zone import TakeCapturedMinion
from hs_sim.engine.effects import AddToHand,Damage,Destroy,Draw,Heal,Silence,Transform
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.health_rules import spell_bonus
from hs_sim.engine.model import DamageKind,Resource,Runes
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import canonical_digest

YETI='CORE_CS2_182';GHOUL='HERO_11bpt';HEAL_TOTEM='NEW1_009'


def registry():
    r=build_registry()
    scripts=dict(kill=lambda c:(Destroy(c.target_id,c.source_id),),
        silence=lambda c:(Silence(c.target_id),),change=lambda c:(Transform(c.target_id,YETI),),
        give=lambda c:(TakeCapturedMinion(MinionReference.capture(c.state.entities[c.target_id]),3-c.player_id,c.source_id),),
        hurt=lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.EFFECT),),
        scratch=lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.EFFECT),),
        fail=lambda c:(AddToHand(c.player_id,'missing.k59',c.source_id),))
    for key,body in scripts.items():
        r.register_behavior('k59.'+key,body);r.register_card(CardDefinition('k59.'+key,key,CardType.SPELL,on_play='k59.'+key,requires_target=key!='fail'))
    r.register_card(CardDefinition('k59.weapon','Ordinary weapon fixture',CardType.WEAPON,cost=1,attack=2,durability=2))
    r.register_card(CardDefinition('k59.other_totem','Other Totem identity fixture',CardType.MINION,health=2,
        metadata=CardMetadata(False,(CardClass.SHAMAN,),None,tribes=('totem',))))
    return r


def sample_decks(r,hero_id):
    chosen=[];identities=set()
    for c in sorted(r.cards.values(),key=lambda c:c.id):
        m=c.metadata
        if (c.kind!=CardType.MINION or m is None or not m.collectible or m.classes!=(CardClass.NEUTRAL,)or
                m.rarity is None or m.rarity.value=='legendary'):continue
        plain=CardDefinition(c.id,c.name,c.kind,cost=c.cost,attack=c.attack,health=c.health,keywords=c.keywords,metadata=m)
        identity=m.deck_identity or c.id
        if c!=plain or identity in identities:continue
        chosen.append(c.id);identities.add(identity)
        if len(chosen)==15:break
    if len(chosen)!=15:raise AssertionError('The experimental30-card sample requires15 distinct existing numeric/keyword minion identities')
    cards=tuple(cid for cid in chosen for _ in range(2));hero=r.card(hero_id);card_class=hero.metadata.classes[0]
    own=DeckSpec(hero_id,hero.initial_hero_power,card_class,cards,Runes(1,1,1)if card_class==CardClass.DEATH_KNIGHT else None)
    enemy=DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,cards)
    policy=DeckPolicy('lab.k59.basic-roles','lab-cn37-basic-roles','experimental',tuple(chosen),pool_complete=False)
    return MatchSetup((own,enemy),policy,'GAME_005',seed=1059,first_player=1)


class BasicHeroRoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hero=2,*,hand=(),board=(),enemy=(),enemy_hand=(),mana=20,seed=1059):
        return Game.from_scenario(Scenario((PlayerSetup(f'HERO_{hero:02}',hero_power_card_id=f'HERO_{hero:02}bp',hand=hand,board=board,deck=(YETI,)*8,mana=mana,max_mana=20,mana_cap=20),
            PlayerSetup('HERO_08',hero_power_card_id='HERO_08bp',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=20,max_mana=20,mana_cap=20)),seed=seed),self.r)
    def entity(self,g,cid,p=1,zone='board'):
        s=g.state;return next(s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid)
    def power(self,g,target=None):g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,target))
    def play(self,g,cid,target=None):
        eid=self.entity(g,cid,zone='hand').id;g.apply(PlayCard(1,eid,target));return eid
    def portable(self,g,factory=registry):
        saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,factory()).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),factory()).snapshot(),saved)
    def test_eleven_complete_new_faces_and_existing_ghoul_life_tap(self):
        data=load_batch();self.assertEqual(len(data['cards']),11);self.assertEqual(tuple(data['basic_totem_ids']),TOTEMS)
        for x in data['cards']:self.assertEqual(canonical_digest(x['record']),x['record_sha256'])
        for x in data['existing_dependencies']:self.assertEqual(reviewed_definition_digest(self.r.card(x['record']['id'])),x['definition_sha256'])
    def test_all_eleven_canonical_hero_power_bindings_follow_original_references(self):
        for row in load_batch()['canonical_roles']:
            h,p=row['hero_record'],row['power_record'];self.assertEqual(h['tags']['HERO_POWER'],p['dbf_id']);self.assertEqual(self.r.card(h['id']).initial_hero_power,p['id']);self.assertEqual(self.r.card(h['id']).metadata.classes,self.r.card(p['id']).metadata.classes)
    def test_two_new_base_heroes_are_starting_roles_not_playable_hero_cards(self):
        for cid in ['HERO_07','HERO_10']:
            c=self.r.card(cid);self.assertEqual((c.kind,c.health),(CardType.HERO,30));self.assertFalse(c.hero_card);self.assertFalse(c.hand_playable)
    def test_default_representative_signature_and_unbound_historical_roles_remain(self):
        r=representative();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667');self.assertIsNone(r.card('HERO_02').initial_hero_power)
    def test_deferred_incomplete_assembly_cannot_be_frozen_or_signed_as_complete(self):
        r=representative(initial_hero_power_bindings=(('HERO_02','HERO_02bp'),),defer_validation=True)
        with self.assertRaises(ValueError):representative(initial_hero_power_bindings=(('HERO_08','HERO_08bp'),))
        with self.assertRaises(Exception):r.freeze()
        with self.assertRaises(Exception):r.fingerprint()
    def test_invalid_duplicate_or_unknown_initial_bindings_fail(self):
        for kwargs in [dict(initial_hero_power_bindings=[('HERO_02','HERO_02bp')]),dict(initial_hero_power_bindings=(('HERO_02','a'),('HERO_02','b'))),dict(initial_hero_power_bindings=(('missing.hero','a'),)),dict(defer_validation=1)]:
            with self.assertRaises((ValueError,RuntimeError)):representative(**kwargs)
    def test_all_eleven_classes_complete_real_thirty_card_experimental_openings(self):
        for i in range(1,12):
            with self.subTest(hero=i):
                g=Game.from_decks(sample_decks(self.r,f'HERO_{i:02}'),self.r)
                if i in (7,10):self.portable(g)
                while g.state.pending_choice is not None:
                    q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
                self.assertEqual(g.state.status,'playing');self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,f'HERO_{i:02}bp')
                if i in (7,10):self.portable(g)
    def test_wrong_initial_power_is_rejected_before_allocating_a_match(self):
        setup=sample_decks(self.r,'HERO_02');wrong=replace(setup.decks[0],hero_power_card_id='HERO_05bp')
        with self.assertRaises(ValueError):Game.from_decks(replace(setup,decks=(wrong,setup.decks[1])),self.r)
    def test_public_totemic_call_is_available_from_own_public_board(self):
        g=self.game();self.assertTrue(any(a['type']=='use_hero_power'for a in g.for_player(1).legal_actions()['actions']));self.power(g);self.assertIn(g.state.entities[g.state.players[1].board[0]].card_id,TOTEMS)
    def test_same_seed_and_actions_produce_identical_totem_and_rng(self):
        a=self.game(seed=144);b=self.game(seed=144);self.power(a);self.power(b);self.assertEqual(a.snapshot(),b.snapshot());self.portable(a)
    def test_each_single_missing_basic_identity_is_the_only_candidate(self):
        for missing in TOTEMS:
            with self.subTest(missing=missing):
                g=self.game(board=tuple(x for x in TOTEMS if x!=missing));self.power(g);self.assertEqual({g.state.entities[i].card_id for i in g.state.players[1].board},set(TOTEMS))
    def test_all_four_basic_totems_disable_manual_use_without_payment_or_rng(self):
        g=self.game(board=TOTEMS);before=g.snapshot();self.assertFalse(any(a['type']=='use_hero_power'for a in g.for_player(1).legal_actions()['actions']))
        with self.assertRaises(IllegalAction):self.power(g)
        self.assertEqual(g.snapshot(),before)
    def test_silenced_basic_identity_still_counts_as_controlled(self):
        g=self.game(hand=('k59.silence',),board=TOTEMS);self.play(g,'k59.silence',self.entity(g,'CS2_052').id)
        with self.assertRaises(IllegalAction):self.power(g)
    def test_opponent_basic_totems_do_not_exclude_own_candidates(self):
        g=self.game(enemy=TOTEMS);self.power(g);self.assertEqual(len(g.state.players[1].board),1);self.assertIn(g.state.entities[g.state.players[1].board[0]].card_id,TOTEMS)
    def test_other_totem_type_does_not_replace_a_missing_basic_identity(self):
        g=self.game(board=(*TOTEMS[:3],'k59.other_totem'));self.power(g);self.assertEqual(len(g.state.players[1].board),5);self.assertIn(HEAL_TOTEM,[g.state.entities[i].card_id for i in g.state.players[1].board])
    def test_transformed_basic_identity_no_longer_blocks_its_slot(self):
        g=self.game(hand=('k59.change',),board=TOTEMS);self.play(g,'k59.change',self.entity(g,'CS2_052').id);self.power(g);self.assertIsNotNone(self.entity(g,'CS2_052'))
    def test_full_board_blocks_totemic_call_before_payment(self):
        g=self.game(board=(YETI,)*7);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.power(g)
        self.assertEqual(g.snapshot(),before)
    def test_summon_record_has_hero_power_cause_and_full_available_family(self):
        g=self.game();self.power(g);row=g.state.card_summon_history[-1];self.assertEqual(row.request.cause.origin,'hero_power');self.assertEqual(tuple(x.card_id for x in row.request.materials),TOTEMS);self.portable(g)
    def test_air_totem_contributes_existing_spell_damage(self):
        g=self.game(board=('CS2_052',));self.assertEqual(spell_bonus(g.state,1,g.registry),1)
    def test_stoneclaw_has_taunt_and_searing_has_one_attack(self):
        self.assertIn(Keyword.TAUNT,self.r.card('CS2_051').keywords);self.assertEqual((self.r.card('CS2_050').attack,self.r.card('CS2_050').health),(1,1))
    def test_healing_totem_heals_friendly_minions_and_itself_but_not_hero(self):
        g=self.game(hand=('k59.hurt','k59.hurt','k59.scratch'),board=(HEAL_TOTEM,YETI));target=self.entity(g,YETI).id;totem=self.entity(g,HEAL_TOTEM).id;self.play(g,'k59.hurt',target);self.play(g,'k59.hurt',g.state.players[1].hero_id);self.play(g,'k59.scratch',totem);g.apply(EndTurn(1));self.assertEqual(g.state.entities[target].health,4);self.assertEqual(g.state.entities[totem].health,2);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,28);self.portable(g)
    def test_healing_totem_does_not_heal_opponent_minions(self):
        g=self.game(hand=('k59.hurt',),board=(HEAL_TOTEM,),enemy=(YETI,));eid=self.entity(g,YETI,2).id;self.play(g,'k59.hurt',eid);g.apply(EndTurn(1));self.assertEqual(g.state.entities[eid].health,3)
    def test_silenced_healing_totem_has_no_end_body(self):
        g=self.game(hand=('k59.hurt','k59.silence'),board=(HEAL_TOTEM,YETI));eid=self.entity(g,YETI).id;self.play(g,'k59.hurt',eid);self.play(g,'k59.silence',self.entity(g,HEAL_TOTEM).id);g.apply(EndTurn(1));self.assertEqual(g.state.entities[eid].health,3)
    def test_steady_shot_deals_two_untargeted_hero_power_damage(self):
        g=self.game(5);self.power(g);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28);self.assertEqual(g.state.players[1].mana,18);self.portable(g)
    def test_steady_shot_is_not_amplified_by_spell_damage(self):
        g=self.game(5,board=('CS2_052',));self.power(g);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28)
    def test_default_steady_shot_rejects_an_invented_explicit_target(self):
        g=self.game(5,enemy=(YETI,));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.power(g,self.entity(g,YETI,2).id)
        self.assertEqual(g.snapshot(),before)
    def test_lesser_heal_restores_two_to_friendly_minion(self):
        g=self.game(9,hand=('k59.hurt',),board=(YETI,));eid=self.entity(g,YETI).id;self.play(g,'k59.hurt',eid);self.power(g,eid);self.assertEqual(g.state.entities[eid].health,5);self.portable(g)
    def test_lesser_heal_can_select_enemy_hero(self):
        g=self.game(9,hand=('k59.hurt',));eid=g.state.players[2].hero_id;self.play(g,'k59.hurt',eid);self.power(g,eid);self.assertEqual(g.state.entities[eid].health,30)
    def test_lesser_heal_is_not_amplified_by_spell_damage(self):
        g=self.game(9,hand=('k59.hurt',),board=('CS2_052',));eid=g.state.players[1].hero_id;self.play(g,'k59.hurt',eid);self.power(g,eid);self.assertEqual(g.state.entities[eid].health,30)
    def test_lesser_heal_requires_original_character_target(self):
        g=self.game(9);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.power(g)
        self.assertEqual(g.snapshot(),before)
    def test_demon_claws_costs_one_and_expires_at_turn_end(self):
        g=self.game(10,mana=1);self.power(g);self.assertEqual(g.state.players[1].mana,0);self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack,1);g.apply(EndTurn(1));self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack,0);self.portable(g)
    def test_demon_claws_composes_with_weapon_and_real_hero_attack(self):
        g=self.game(10,hand=('k59.weapon',));self.play(g,'k59.weapon');self.power(g);self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack,3);g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27)
    def test_ghoul_charge_uses_existing_full_charged_undead(self):
        g=self.game(11);self.power(g);e=self.entity(g,GHOUL);self.assertEqual((e.attack,e.health),(1,1));self.assertIn(Keyword.CHARGE,e.keywords);g.apply(Attack(1,e.id,g.state.players[2].hero_id));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,29);self.portable(g)
    def test_ghoul_dies_on_its_controller_end_and_adds_a_corpse(self):
        g=self.game(11);self.power(g);eid=self.entity(g,GHOUL).id;g.apply(EndTurn(1));self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertEqual(g.state.players[1].resources.get(Resource.CORPSES,0),1)
    def test_silenced_ghoul_does_not_keep_printed_end_death(self):
        g=self.game(11,hand=('k59.silence',));self.power(g);eid=self.entity(g,GHOUL).id;self.play(g,'k59.silence',eid);g.apply(EndTurn(1));self.assertEqual(g.state.entities[eid].zone,Zone.BOARD)
    def test_ghoul_transfer_follows_new_controller_end(self):
        g=self.game(11,hand=('k59.give',));self.power(g);eid=self.entity(g,GHOUL).id;self.play(g,'k59.give',eid);g.apply(EndTurn(1));self.assertEqual(g.state.entities[eid].zone,Zone.BOARD);g.apply(EndTurn(2));self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.portable(g)
    def test_full_board_blocks_ghoul_charge_before_payment(self):
        g=self.game(11,board=(YETI,)*7);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.power(g)
        self.assertEqual(g.snapshot(),before)
    def test_new_warlock_role_uses_real_life_tap(self):
        g=self.game(7);self.power(g);self.assertEqual(len(g.state.players[1].hand),1);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,28);self.portable(g)
    def test_queries_do_not_change_rng_or_any_role_state(self):
        g=self.game(board=TOTEMS[:3]);before=g.snapshot()
        for _ in range(2):g.for_player(1).observe();g.for_player(2).observe();g.legal_actions()
        self.assertEqual(g.snapshot(),before)
    def test_unknown_original_failure_rolls_back_role_state(self):
        g=self.game(10,hand=('k59.fail',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k59.fail')
        self.assertEqual(g.snapshot(),before)


if __name__=='__main__':unittest.main()
