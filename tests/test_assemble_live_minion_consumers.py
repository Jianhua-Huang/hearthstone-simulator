"""Real acquired Deathrattles, ordinary forced combat and native Prepare."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import assemble_live_minion_consumers as cards
from hs_sim.cards.constructed import build_registry
from hs_sim.cards.native_assemble_entry_cards import CARETAKER, POOL_ID
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, TargetSpec, UseHandAction, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChoiceOption, CopyMinion, Destroy, InvokeBehavior,
    RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha

ROCK, HOG = cards.SOURCES
LOOT, RUST, CLEANER, HOUR, PRIMORDIAL, DRAGON = cards.DEPENDENCIES
P='k444.'
N,A,B,WEAPON,WATCH,FAIL,REENTER,KILL,MUTE,COPY,BASE,BACK=(P+x for x in (
    'n','a','b','weapon','watch','fail','reenter','kill','mute','copy','base','back'))
COIN='GAME_005'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
CTX=GenerationContext('k444-exact-reviewed-native-domains','experimental')


def recipe(primary,secondary=None,half='bottom'):
    return AssembleRecipe(primary,secondary or primary,half).card_id


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=build_registry();r._version+='.k444.'+mode
    for cid,attack in ((N,1),(A,1),(B,2)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=20,metadata=META))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,attack=1,durability=2,metadata=META))
    def fail(c):raise ResolutionError('K444 deliberate native consumer failure')
    def reenter(c):
        e=c.state.entities[c.target_id]
        return (SummonStoredCard(CardReference.capture(e),e.controller),)
    r.register_behavior(FAIL,fail);r.register_behavior(REENTER,reenter)
    scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        MUTE:lambda c:(Silence(c.target_id),),COPY:lambda c:(CopyMinion(c.target_id,1,mode='current'),),
        BASE:lambda c:(CopyMinion(c.target_id,1,mode='base'),),BACK:lambda c:(ReturnToHand(c.target_id),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    if mode in ('grant_wait','grant_fail','attack_wait'):
        def recipient(c):
            target=c.state.entities.get(c.event.target_id)
            return target is not None and target.card_id.startswith('assemble:')
        def watch(c):
            if mode=='grant_fail':raise ResolutionError('K444 actual acquired-ability notification failure')
            target=c.event.target_id
            return (RequestChoice(1,(ChoiceOption('go','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(FAIL,c.source_id,1),)),
                ChoiceOption('back','Reenter',(ReturnToHand(target),InvokeBehavior(REENTER,c.source_id,1,target)))),c.source_id),)
        r.register_trigger_condition(P+'recipient',recipient);r.register_behavior(WATCH,watch)
        event='attack_declared'if mode=='attack_wait'else'ability_granted'
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
            limited_triggers=(LimitedTriggerSpec(event,WATCH,condition_id=P+'recipient'),)))
    domains={'rock_offer':(ROCK,HOUR,CLEANER),'hog_offer':(HOG,PRIMORDIAL,DRAGON),
        'mismatch':(RUST,HOG,CLEANER)}
    if mode in domains:
        r.register_pool(PoolDefinition(POOL_ID,'k444-complete-three-review-members',CTX.target_id,CTX.mode,
            tuple(PoolMember(cid)for cid in domains[mode]),complete=True))
    r.validate();return r


class AssembleLiveMinionTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),mode='normal',mana=20,weapon=False):
        if mode in ('grant_wait','grant_fail','attack_wait'):board=board+(WATCH,)
        hero='HERO_05'if mode=='rock_offer'else'HERO_01'
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=(COIN,)*20,
            mana=mana,max_mana=mana,mana_cap=40),PlayerSetup('HERO_08',board=enemy,deck=(COIN,)*20,
                weapon_card_id=WEAPON if weapon else None)),seed=4,generation_context=CTX),fixture(mode))

    def ids(self,g,cid,zone='board',p=1):
        return [i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid]

    def play(self,g,cid,target=None,position=None):
        eid=self.ids(g,cid,'hand')[0];g.apply(PlayCard(1,eid,target,position));return eid

    def gained(self,g,eid):
        return [a for a in g.state.entities[eid].abilities if a.kind=='deathrattle'and a.deathrattle_copied_from is not None]

    def choose(self,g,key='go'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def portable(self,g,mode='normal'):
        saved=json.loads(json.dumps(g.snapshot()));reader=fixture(mode,'reader');self.assertIsNot(reader,g.registry)
        other=Game.from_snapshot(saved,reader);self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        self.assertEqual(g.snapshot(),saved)
        for p in (1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in ('deathrattle_copied_from','CopiedDeathrattleSource','rng_state','resolution_frame','behavior_id'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_a_eight_complete_rows_sixteen_faces_and_exact_both_native_self_definitions(self):
        d=cards.load_batch();r=fixture();rows={x['record']['id']:x for x in d['existing_dependencies']}
        self.assertEqual(len(rows),8);self.assertEqual(len(d['official_observations']),16)
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']),o['response_sha256']);check_face(rows[o['card_id']]['record'],o['face'],o['locale'])
        for cid,row in rows.items():self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
        for cid in cards.SOURCES:
            original=asdict(r.card(cid));new=asdict(r.card(recipe(cid)));new['id']=cid
            self.assertEqual(new,original);self.assertEqual(recipe_options(r,cid,cid),())

    def test_b_raw_and_self_rockfang_acquire_two_complete_physical_neighbors_then_draw_twice(self):
        for cid in (ROCK,recipe(ROCK)):
            g=self.game((cid,KILL),(LOOT,LOOT));neighbors=list(g.state.players[1].board);source=self.play(g,cid,position=1)
            acquired=self.gained(g,source);self.assertEqual(len(acquired),2)
            self.assertEqual([a.deathrattle_copied_from.origin.entity_id for a in acquired],neighbors)
            self.assertEqual(len({a.id for a in acquired}),2);self.play(g,KILL,source)
            self.assertEqual(len(g.state.draw_history),2);self.assertTrue(all(i in g.state.players[1].board for i in neighbors))

    def test_c_replacing_rockfang_suffix_removes_acquisition_and_uses_weapon_body(self):
        cid=recipe(ROCK,RUST);g=self.game((cid,),(LOOT,LOOT),weapon=True);source=self.play(g,cid,position=1)
        self.assertEqual(self.gained(g,source),[]);self.assertIsNone(g.state.players[2].weapon_id)

    def test_d_live_end_prefix_uses_current_neighbors_without_an_old_battlecry(self):
        cid=recipe(ROCK,HOUR,'top');g=self.game((cid,),(LOOT,LOOT));source=self.play(g,cid,position=1)
        self.assertEqual(self.gained(g,source),[]);self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords)
        g.apply(EndTurn(1));self.assertEqual(len(self.gained(g,source)),2);self.portable(g)

    def test_e_natural_death_has_no_live_self_benefit_and_does_not_replay_original_suffix(self):
        for original in cards.SOURCES:
            cid=recipe(original,LOOT,'top');g=self.game((cid,KILL),(LOOT,LOOT),enemy=(A,B));source=self.play(g,cid,position=1)
            self.play(g,KILL,source);self.assertEqual(g.state.draw_history,[]);self.assertEqual(g.state.character_attack_history,[])
            self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)

    def test_f_acquired_material_survives_current_copy_but_not_printed_base_or_silence(self):
        cid=recipe(ROCK);g=self.game((cid,COPY,BASE,MUTE),(LOOT,LOOT));source=self.play(g,cid,position=1)
        self.play(g,COPY,source);current=next(i for i in self.ids(g,cid)if i!=source)
        self.assertEqual(len(self.gained(g,current)),2);self.play(g,BASE,source)
        base=next(i for i in self.ids(g,cid)if i not in(source,current));self.assertEqual(self.gained(g,base),[])
        self.play(g,MUTE,source);self.assertEqual(self.gained(g,source),[]);self.portable(g)

    def test_g_silenced_original_neighbor_has_no_declaration_to_gain(self):
        cid=recipe(ROCK);g=self.game((cid,MUTE),(LOOT,LOOT));left=g.state.players[1].board[0]
        self.play(g,MUTE,left);source=self.play(g,cid,position=1);self.assertEqual(len(self.gained(g,source)),1)

    def test_h_grant_wait_restores_complete_material_and_failed_resume_keeps_original_boundary(self):
        cid=recipe(ROCK);g=self.game((cid,),(LOOT,LOOT),mode='grant_wait');source=self.play(g,cid,position=1)
        self.assertEqual(len(self.gained(g,source)),2);reader=self.portable(g,'grant_wait');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(reader);self.assertEqual(g.snapshot(),reader.snapshot())
        self.assertEqual(len(self.gained(g,source)),2)

    def test_i_grant_notification_failure_rolls_back_payment_attachments_and_allocators(self):
        cid=recipe(ROCK);g=self.game((cid,),(LOOT,LOOT),mode='grant_fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,cid,position=1)
        self.assertEqual(g.snapshot(),saved)

    def test_j_raw_and_self_hound_keep_two_original_enemy_attacks_with_derived_source_stats(self):
        for cid in (HOG,recipe(HOG)):
            g=self.game((cid,),enemy=(A,B));source=self.play(g,cid)
            self.assertEqual(len(g.state.character_attack_history),2);self.assertEqual(g.state.entities[source].health,9)
            self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[16,16])

    def test_k_hound_body_under_rock_prefix_keeps_rock_stats_and_has_no_prepare_or_copied_deaths(self):
        cid=recipe(ROCK,HOG);g=self.game((cid,),enemy=(A,));source=self.play(g,cid)
        self.assertEqual(g.state.entities[source].health,1);self.assertEqual(len(g.state.character_attack_history),1)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,17)
        self.assertEqual(g.registry.card(cid).hand_actions,());self.assertEqual(self.gained(g,source),[])

    def test_l_hound_prefix_keeps_prepare_but_selected_weapon_body_drops_old_attacks(self):
        cid=recipe(HOG,RUST);g=self.game((cid,),enemy=(A,B),weapon=True);self.play(g,cid)
        self.assertEqual([a.kind for a in g.registry.card(cid).hand_actions],['prepare'])
        self.assertEqual(g.state.character_attack_history,[]);self.assertIsNone(g.state.players[2].weapon_id)

    def test_m_borrowed_taunt_prefix_removes_prepare_and_keeps_native_forced_attack_body(self):
        cid=recipe(HOG,PRIMORDIAL,'top');g=self.game((CARETAKER,),enemy=(A,B),mode='hog_offer');self.play(g,CARETAKER)
        q=g.state.pending_choice;self.assertIn(cid,[o.card_id for o in q.options]);self.choose(g,next(o.id for o in q.options if o.card_id==cid))
        source=self.play(g,cid)
        self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords);self.assertEqual(g.registry.card(cid).hand_actions,())
        self.assertEqual((len(g.state.character_attack_history),g.state.entities[source].health),(2,9))

    def test_n_native_attack_wait_restores_original_guards_and_completes_only_once(self):
        cid=recipe(HOG,PRIMORDIAL,'top');g=self.game((cid,),enemy=(A,B),mode='attack_wait');source=self.play(g,cid)
        reader=self.portable(g,'attack_wait');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(reader);self.assertEqual(g.snapshot(),reader.snapshot())
        self.assertEqual((len(g.state.character_attack_history),g.state.entities[source].health),(2,9))

    def test_o_reentry_of_same_assembled_defender_cancels_original_attacks(self):
        cid=recipe(HOG,PRIMORDIAL,'top');g=self.game((cid,),enemy=(A,B),mode='attack_wait');source=self.play(g,cid)
        self.choose(g,'back');self.assertEqual(g.state.entities[source].health,12)
        self.assertEqual(len(g.state.character_attack_history),1)
        self.assertEqual(g.state.character_attack_history[0].terminal.reason,'defender_left_original_board_residence')
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[20,20]);self.portable(g,'attack_wait')

    def test_p_true_beast_offer_keeps_rock_primary_and_end_prefix_then_gains_adjacent_deaths(self):
        cid=recipe(ROCK,HOUR,'top');g=self.game((CARETAKER,),(LOOT,LOOT),mode='rock_offer');self.play(g,CARETAKER)
        q=g.state.pending_choice;self.assertIn(cid,[o.card_id for o in q.options]);self.portable(g,'rock_offer')
        self.choose(g,next(o.id for o in q.options if o.card_id==cid));source=self.play(g,cid,position=1)
        self.assertEqual(self.gained(g,source),[]);g.apply(EndTurn(1));self.assertEqual(len(self.gained(g,source)),2)
        self.portable(g,'rock_offer')

    def test_q_true_mismatch_low_primary_gets_hound_prepare_and_original_turn_lock(self):
        cid=recipe(RUST,HOG,'top');g=self.game((MISMATCH,),mode='mismatch',weapon=True);self.play(g,MISMATCH)
        q=g.state.pending_choice;self.assertIn(cid,[o.card_id for o in q.options]);self.choose(g,next(o.id for o in q.options if o.card_id==cid))
        source=self.ids(g,cid,'hand')[0];mana=g.state.players[1].mana;g.apply(UseHandAction(1,source,'prepare'))
        self.assertEqual(g.registry.card(cid).cost,3)
        self.assertEqual(g.state.players[1].mana,mana-2);self.assertEqual(g.quote_cost(source).amount,0)
        saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,cid)
        self.assertEqual(g.snapshot(),saved);self.portable(g,'mismatch')
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,cid)
        self.assertIsNone(g.state.players[2].weapon_id);self.assertEqual(g.state.character_attack_history,[]);self.portable(g,'mismatch')

    def test_r_true_mismatch_hound_suffix_uses_low_primary_attack_and_preserves_trade_prefix(self):
        cid=recipe(RUST,HOG);g=self.game((MISMATCH,),enemy=(A,A),mode='mismatch');self.play(g,MISMATCH)
        q=g.state.pending_choice;self.assertIn(cid,[o.card_id for o in q.options]);self.choose(g,next(o.id for o in q.options if o.card_id==cid));self.play(g,cid)
        self.assertEqual(len(g.state.character_attack_history),2);self.assertEqual([a.kind for a in g.registry.card(cid).hand_actions],['trade'])
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[20-g.registry.card(RUST).attack]*2);self.portable(g,'mismatch')

    def test_s_seven_cost_prepared_assembled_hound_invests_six_mana_not_a_fixed_one(self):
        cid=recipe(HOG,RUST);g=self.game((cid,),mana=7,weapon=True);source=self.ids(g,cid,'hand')[0]
        g.apply(UseHandAction(1,source,'prepare'));self.assertEqual(g.state.players[1].mana,1);self.assertEqual(g.quote_cost(source).amount,0)
        with self.assertRaises(IllegalAction):self.play(g,cid)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,cid);self.assertIsNone(g.state.players[2].weapon_id)

    def test_t_changed_whole_definition_or_duplicate_source_fails_without_silent_fallback(self):
        r=fixture.__wrapped__();r._cards[HOG]=replace(r.card(HOG),hand_actions=())
        with self.assertRaises(TargetValidationError):cards.register_assemble_live_minion_consumers(r)
        r=fixture.__wrapped__()
        with self.assertRaises(ValueError):cards.register_assemble_live_minion_consumers(r)


if __name__=='__main__':unittest.main()
