"""Native five-spell effects and the complete local Rogue Mentor chain."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
from pathlib import Path
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import rogue_teacher_spells as native
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    CastWhenDrawnSpec, DeckSpec, EndTurn, Game, Keyword, PlayCard, PlayerSetup,
    ResolutionError, Scenario, SelectChoice, Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (ChoiceOption, Draw, GainArmor, InvokeBehavior,
                                  ReplaceHero, RequestChoice)
from hs_sim.engine.pools import resolve_candidates, sample_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.student_teaching import QUERY
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format
from tools import card_batch as cb

ROOT=Path(__file__).resolve().parents[1]
P='rogue.fix.test.';UNIT=P+'unit';DR=P+'dr';WAIT=P+'waitdr';MENTOR='TIME_704';PUPIL='TIME_704t'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    f=build_cn37_local_pool_format();r=f.registry
    # Match the two existing public host aliases without changing membership.
    original=r.pool('constructed.minions',f.context)
    for name in ('representative.attack-cost-minions','representative.legendary-dragons'):
        r.register_pool(replace(original,id=name,version='ui-standard-match-full-minions-v1:'+original.version))
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,cost=5,attack=1,health=20,metadata=META))
    r.register_behavior(P+'armor',lambda c:(GainArmor(c.player_id,1),))
    r.register_behavior(P+'fail',lambda c:(_ for _ in ()).throw(ValueError('deliberate Rogue continuation fault')))
    def wait(c):
        other=next((c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==DR),None)
        move=()if other is None else(ChoiceOption('move','Move the next drawn card',(
            MoveCard(CardReference.capture(other),c.player_id,Zone.DECK,'top',source_id=c.source_id),GainArmor(c.player_id,1))),)
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fail','Rollback',(InvokeBehavior(P+'fail',c.source_id,c.player_id),)),*move),c.source_id),)
    r.register_behavior(P+'wait',wait)
    for cid,body in ((DR,P+'armor'),(WAIT,P+'wait')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=1,health=2,metadata=META,deathrattle=body))
    r.register_behavior(P+'noop',lambda c:())
    for name,classes in (('own',(CardClass.ROGUE,)),('mage',(CardClass.MAGE,)),
            ('druid',(CardClass.DRUID,)),('neutral',(CardClass.NEUTRAL,)),('dual',(CardClass.ROGUE,CardClass.MAGE))):
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+'noop',metadata=CardMetadata(False,classes,None)))
    r.register_behavior(P+'draw2',lambda c:(Draw(c.player_id,2,c.source_id),))
    r.register_behavior(P+'magehero',lambda c:(ReplaceHero(c.player_id,'HERO_08'),))
    for name in ('draw2','magehero'):
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,metadata=META))
    r.register_card(CardDefinition(P+'cast',P+'cast',CardType.SPELL,on_play=P+'noop',metadata=META,
        keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec(replacement=True)))
    return f


def candidates(f):
    return resolve_candidates(f.registry,f.context,'constructed.past.spells',QUERY,
        current_class=CardClass.ROGUE,source_card_id=MENTOR,exclude_source_by_rule=True)


class RogueTeacherSpellTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role).registry)

    def game(self,hand=(),deck=(UNIT,)*16,board=(),enemy=(UNIT,),seed=1,hero='HERO_03'):
        f=fixture()
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,deck=deck,board=board,
            mana=60,max_mana=60,mana_cap=60),PlayerSetup('HERO_08',board=enemy,deck=(UNIT,)*16)),
            seed=seed,generation_context=f.context),f.registry,mode='debug')

    def price(self,g,cid):
        e=self.entity(g,cid)
        return quote_unselected_cost(g.state,g.registry,e).amount

    def test_all_five_full_rows_and_ten_primary_faces_are_pinned(self):
        d=native.load_batch();raw={x['id']:x for x in cb.read(ROOT/d['source'])}
        self.assertEqual(len(d['official_observations']),10)
        for cid,row in d['cards'].items():self.assertEqual(row['record'],raw[cid])
        for obs in d['official_observations']:
            cb.check_face(raw[obs['card_id']],obs['face'],obs['locale'])
        native.validate_native(fixture().registry,d)
        self.assertFalse(d['formal_pool_complete']or d['cn_calibrated'])

    def test_six_candidates_and_original_201_member_prefix_are_preserved(self):
        f=fixture();d=native.load_batch();pool=f.registry.pool('constructed.past.spells',f.context)
        self.assertEqual([x.card_id for x in pool.members[:201]],d['prior_member_ids'])
        self.assertEqual(len(pool.members),206)
        self.assertEqual([x.card_id for x in candidates(f)],d['teacher_candidate_ids'])
        self.assertEqual([x.weight for x in candidates(f)],[1]*6)
        for cls in (CardClass.DRUID,CardClass.MAGE):
            expected=cb.read(ROOT/'data/cards/past-teacher-mage-source-v1.json')[cls.value+'_actual']
            actual=resolve_candidates(f.registry,f.context,pool.id,QUERY,current_class=cls,source_card_id=MENTOR,exclude_source_by_rule=True)
            self.assertEqual([asdict(x)for x in actual],expected)

    def test_other_sources_and_unreviewed_classes_remain_rejected(self):
        f=fixture()
        for source,cls in ((MENTOR,CardClass.WARRIOR),('TIME_861',CardClass.ROGUE),(UNIT,CardClass.ROGUE)):
            with self.subTest(source=source,cls=cls),self.assertRaises(UnsupportedDefinitionError):
                resolve_candidates(f.registry,f.context,'constructed.past.spells',QUERY,
                    current_class=cls,source_card_id=source,exclude_source_by_rule=True)

    def test_quasar_moves_original_hand_then_discounts_all_deck_cards(self):
        g=self.game(('GDB_467',P+'mage',UNIT),deck=(UNIT,UNIT))
        old=g.state;held=set(old.players[1].hand[1:]);old_deck=set(old.players[1].deck)
        source=self.play(g,'GDB_467');s=g.state
        self.assertFalse(s.players[1].hand)
        self.assertEqual(set(s.players[1].deck),held|old_deck)
        self.assertNotIn(source,s.players[1].deck)
        self.assertEqual(s.play_history[-1].cost,8)
        for i in s.players[1].deck:
            e=s.entities[i]
            self.assertEqual(quote_unselected_cost(s,g.registry,e).amount,max(0,g.registry.card(e.card_id).cost-3))
        self.portable(g)

    def test_empty_hand_quasar_still_discounts_without_shuffle_or_rng(self):
        g=self.game(('GDB_467',),deck=(UNIT,UNIT))
        old=g.snapshot();deck=list(g.state.players[1].deck)
        self.play(g,'GDB_467')
        self.assertEqual(g.state.players[1].deck,deck)
        self.assertEqual(g.snapshot()['rng_state'],old['rng_state'])
        self.assertTrue(all(quote_unselected_cost(g.state,g.registry,g.state.entities[i]).amount==2 for i in deck))

    def test_smokescreen_draws_five_then_executes_hand_deathrattles(self):
        g=self.game(('ONY_031',),deck=(DR,UNIT,DR,UNIT,UNIT))
        self.play(g,'ONY_031');s=g.state
        self.assertEqual(len(s.draw_history),5)
        self.assertTrue(all(x.completed for x in s.draw_history))
        self.assertEqual(s.entities[s.players[1].hero_id].armor,2)
        self.assertEqual(len(s.deathrattle_history),2)
        self.assertFalse(s.death_history)
        self.assertEqual(sum(s.entities[i].card_id==DR for i in s.players[1].hand),2)

    def test_smokescreen_real_loot_hoarder_draw_is_after_the_five_roots(self):
        g=self.game(('ONY_031',),deck=('CORE_EX1_096',UNIT,UNIT,UNIT,UNIT,UNIT))
        self.play(g,'ONY_031');s=g.state
        self.assertEqual(len(s.draw_history),6)
        self.assertEqual([x.source_id for x in s.draw_history[:5]],[s.draw_history[0].source_id]*5)
        self.assertNotEqual(s.draw_history[-1].source_id,s.draw_history[0].source_id)
        self.assertEqual(len(s.deathrattle_history),1)
        self.assertTrue(any(s.entities[i].card_id=='CORE_EX1_096'for i in s.players[1].hand))

    def test_smokescreen_burns_and_fatigue_do_not_trigger(self):
        g=self.game(('ONY_031',)+(UNIT,)*9,deck=(DR,DR,DR,DR,DR))
        self.play(g,'ONY_031')
        self.assertEqual([x.outcome for x in g.state.draw_history],['hand','burned','burned','burned','burned'])
        self.assertEqual(len(g.state.deathrattle_history),1)
        g=self.game(('ONY_031',),deck=());self.play(g,'ONY_031')
        self.assertEqual(len(g.state.draw_history),5);self.assertFalse(g.state.deathrattle_history)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].damage,15)

    def test_smokescreen_does_not_borrow_a_draw_cast_replacement_child(self):
        g=self.game(('ONY_031',),deck=(P+'cast',DR,UNIT,UNIT,UNIT,UNIT))
        self.play(g,'ONY_031')
        self.assertEqual(len(g.state.draw_history),6)
        self.assertTrue(any(x.parent_id is not None for x in g.state.draw_history))
        self.assertFalse(g.state.deathrattle_history)

    def test_smokescreen_waiting_deathrattle_restores_and_resumes_once(self):
        g=self.game(('ONY_031',),deck=(WAIT,DR,UNIT,UNIT,UNIT))
        self.play(g,'ONY_031');self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(g.state.draw_history),5)
        other=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before)
        for match in (g,other):self.choose(match)
        self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)
        self.portable(g)

    def test_smokescreen_rejects_borrowed_epoch_and_skips_a_departed_draw(self):
        from hs_sim.engine.physical_draw_groups import TriggerDrawnDeathrattle
        from hs_sim.engine.continuations import FrameCodec
        g=self.game(('ONY_031',),deck=(WAIT,DR,UNIT,UNIT,UNIT));source=self.play(g,'ONY_031')
        entity=self.entity(g,DR);reference=CardReference.capture(entity)
        effect=TriggerDrawnDeathrattle(1,source,2,reference)
        effect.validate_in_state(g.state,g.registry)
        forged=replace(effect,card=replace(reference,zone_epoch=reference.zone_epoch+1))
        with self.assertRaises(ValueError):forged.validate_in_state(g.state,g.registry)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g._state)
        with self.assertRaises(ValueError):codec.encode(forged)
        self.choose(g,'move')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
        self.assertEqual(g.state.entities[entity.id].zone,Zone.DECK)
        self.assertEqual(len(g.state.deathrattle_history),1)

    def test_draw_discount_uses_this_turn_and_two_four_cost_summons(self):
        g=self.game((P+'draw2','TOY_519'))
        self.assertEqual(self.price(g,'TOY_519'),8)
        self.play(g,P+'draw2');self.assertEqual(self.price(g,'TOY_519'),6)
        self.play(g,'TOY_519');s=g.state
        self.assertEqual(s.play_history[-1].cost,6)
        self.assertEqual(len(s.players[1].board),2)
        self.assertTrue(all(g.registry.card(s.entities[i].card_id).cost==4 for i in s.players[1].board))

    def test_draw_discount_fatigue_does_not_count_and_full_board_keeps_batch_sampling(self):
        g=self.game((P+'draw2','TOY_519'),deck=(),board=(UNIT,)*7)
        self.play(g,P+'draw2');self.assertEqual(self.price(g,'TOY_519'),8)
        f=fixture();rows=resolve_candidates(g.registry,f.context,'constructed.cards',native.FOUR,
            source_card_id='TOY_519',player_id=1,exclude_source_by_rule=True)
        rng=Random();rng.setstate(g._rng.getstate());expected=sample_candidates(rng,rows,2,replacement=True)
        self.play(g,'TOY_519')
        self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(g.state.pool_summon_history[-1].selected,expected)

    def test_other_class_discount_uses_original_faces_excludes_neutral_and_shared_class(self):
        g=self.game((P+'mage',P+'druid',P+'own',P+'neutral',P+'dual','VAC_700'),enemy=(UNIT,)*3)
        for cid in ('mage','druid','own','neutral','dual'):self.play(g,P+cid)
        self.assertEqual(self.price(g,'VAC_700'),6)
        self.play(g,'VAC_700');self.assertEqual(g.state.play_history[-1].cost,6)
        self.assertEqual(len(g.state.players[2].board),1)
        self.assertEqual(len(g.state.death_history),2)
        self.portable(g)

    def test_other_class_quote_recaptures_current_hero_without_rewriting_old_plays(self):
        g=self.game((P+'mage',P+'own',P+'magehero','VAC_700'))
        self.play(g,P+'mage');self.assertEqual(self.price(g,'VAC_700'),7)
        self.play(g,P+'own');self.play(g,P+'magehero')
        self.assertEqual(g.state.players[1].hero_class,CardClass.MAGE)
        self.assertEqual(self.price(g,'VAC_700'),7)

    def test_random_destruction_with_one_or_no_enemy_uses_available_targets(self):
        g=self.game(('VAC_700',),enemy=(UNIT,));self.play(g,'VAC_700')
        self.assertFalse(g.state.players[2].board)
        g=self.game(('VAC_700',),enemy=());rng=g.snapshot()['rng_state'];self.play(g,'VAC_700')
        self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_seven_damage_precedes_seven_draws_and_cannot_target_hero(self):
        g=self.game(('WW_410',));before=g.snapshot()
        from hs_sim.engine.errors import IllegalAction
        with self.assertRaises(IllegalAction):self.play(g,'WW_410',g.state.players[2].hero_id)
        self.assertEqual(g.snapshot(),before)
        target=g.state.players[2].board[0];self.play(g,'WW_410',target)
        self.assertEqual(g.state.entities[target].health,13)
        self.assertEqual(len(g.state.draw_history),7)
        self.portable(g)

    def test_each_of_the_six_candidates_is_taught_and_cast_by_the_original_pupil(self):
        rows=candidates(fixture())
        for cid in native.load_batch()['teacher_candidate_ids']:
            with self.subTest(card=cid):
                seed=next(i for i in range(1000)if cid in sample_candidates(Random(i),rows,3,replacement=False))
                g=self.game((MENTOR,),seed=seed,enemy=(UNIT,UNIT))
                self.play(g,MENTOR);self.assertIsNotNone(g.state.pending_choice)
                option=next(o.id for o in g.state.pending_choice.options if o.card_id==cid)
                self.choose(g,option)
                target=g.state.players[2].board[0]if cid=='WW_410'else None
                self.play(g,PUPIL,target)
                casts=[x for x in g.state.cast_history if x.card_id==cid]
                self.assertEqual(len(casts),1);self.assertTrue(casts[0].completed)
                self.assertEqual(casts[0].origin,'effect')

    def test_player_port_teacher_choice_and_pupil_keep_information_boundary(self):
        g=self.game((MENTOR,));port=g.for_player(1);legal=port.legal_actions()
        command=next(x for x in legal['actions']if x['type']=='play_card')
        reply=port.submit({'revision':legal['revision'],'action':command});self.assertTrue(reply['accepted'])
        other=self.portable(g)
        choice=g.state.pending_choice;selected=choice.options[0].id
        for match in (g,other):match.apply(SelectChoice(1,match.state.pending_choice.id,(selected,)))
        self.assertEqual(g.snapshot(),other.snapshot())

    def test_original_discovery_game_prefix_reaches_the_previously_rejected_action(self):
        from web_ui.autoplay_checks import facts
        f=fixture();path=ROOT/'outputs/environment-r13-20261103/decks/discovery_v2.json'
        doc=cb.read(path);specs=[DeckSpec(v['hero_card_id'],v['hero_power_card_id'],CardClass(v['card_class']),tuple(v['cards']))for v in doc['decks'].values()]
        g=Game.from_decks(f.match_setup(tuple(specs),seed=2026110301,first_player=1),f.registry)
        rows=[json.loads(s)for s in(ROOT/'outputs/environment-r13-20261103/discovery_v2/run/private/A-1-steps.jsonl').read_text('utf-8').splitlines()]
        def normalize(value):
            value=json.loads(json.dumps(value))
            for e in value['entities'].values():e['keywords']=sorted(e['keywords'])
            return value
        accepted=0
        for row in rows:
            self.assertEqual(normalize(facts(g)),normalize(row['before']),f"before step{row['step']}")
            port=g.for_player(row['actor']);reply=port.submit({'revision':port.legal_actions()['revision'],'action':row['action']})
            self.assertTrue(reply['accepted'],f"step{row['step']}: {reply.get('error')}")
            if row['step']==164:
                self.assertEqual(accepted,164);self.assertIsNotNone(g.state.pending_choice)
                self.assertEqual(g.state.players[1].hero_class,CardClass.ROGUE)
                saved=g.snapshot();reader=fixture('normal','independent-reader').registry
                other=Game.from_snapshot(saved,reader);self.assertEqual(other.snapshot(),saved)
                selected=g.state.pending_choice.options[0].id
                for match in (g,other):self.choose(match,selected)
                self.assertEqual(g.snapshot(),other.snapshot())
                from hs_sim.engine.replay import build_replay,replay
                self.assertEqual(replay(build_replay(other),reader).snapshot(),other.snapshot())
                return
            self.assertEqual(normalize(facts(g)),normalize(row['after']),f"after step{row['step']}")
            accepted+=1
        self.fail('Missing recorded step164')
