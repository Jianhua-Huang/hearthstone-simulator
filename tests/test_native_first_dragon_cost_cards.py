"""Current first-Dragon qualification from complete original submitted inputs."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.native_first_dragon_cost_cards import CARD, AURA, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CostAuraSpec,
    CostSpec, EndTurn, Game, IllegalAction, PlayCard, PlayerSetup, Rarity, Scenario,
    SelectChoice, SnapshotError, TargetSpec, TribeChangeSpec, Zone)
from hs_sim.engine.costs import (capture_cost_input, capture_generated_quote_fact, quote_input,
    validate_first_play_cost_prefix)
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.repeat_matching import validate_cost_quote_fact
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference

P = 'k149.'
PLAIN, DRAGON, FREE, ALL, UNKNOWN, WAIT = (P+n for n in ('plain','dragon','free','all','unknown','waiting'))
META = CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())


@lru_cache(maxsize=None)
def registry(reader=False):
    r = build_registry()
    def fail(c):
        raise ResolutionError('K149 deliberate failure')
    r.register_behavior(P+'fail',fail)
    def source(c):
        return next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CARD)
    def wait(c):
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue'),
            ChoiceOption('silence','Silence source',(Silence(source(c)),)),
            ChoiceOption('bad','Fail after silence',(Silence(source(c)),InvokeBehavior(P+'fail',c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(P+'wait',wait)
    for cid,tribes,cost,body in ((PLAIN,(),4,None),(DRAGON,('dragon',),5,None),
            (FREE,('dragon',),0,None),(ALL,('all',),6,None),(UNKNOWN,None,3,None),
            (WAIT,('dragon',),5,P+'wait'),(P+'failing',('dragon',),5,P+'fail')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,health=8,attack=1,
            battlecry=body,metadata=replace(META,tribes=tribes)))
    scripts = {
        'summon':lambda c:(Summon(c.player_id,CARD),),
        'silence':lambda c:(Silence(c.target_id),),
        'destroy':lambda c:(Destroy(c.target_id,c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'transform':lambda c:(Transform(c.target_id,PLAIN),),
        'take':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'sleep':lambda c:(MakeDormant(c.target_id,None),),
        'wake':lambda c:(AwakenMinion(next(i for i in c.state.players[c.player_id].board
            if c.state.entities[i].dormancy is not None)),),
    }
    for name,operation,tribes in (('dragon','add',('dragon',)),('strip','remove',('dragon',)),
            ('all','set',('all',)),('plain','set',())):
        def change(c,operation=operation,tribes=tribes):
            entity=c.state.entities[c.target_id]
            reference=MinionReference.capture(entity) if entity.zone==Zone.BOARD else CardReference.capture(entity)
            return (ChangeMinionTribes(reference,
                TribeChangeSpec(operation,tribes),c.source_id),)
        scripts['tribe_'+name]=change
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        kwargs = {}
        if name not in ('summon','wake'):
            kwargs['targeting']=TargetSpec(zones=(Zone.HAND,Zone.BOARD),kinds=(CardType.MINION,),relation='friendly')
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,metadata=META,**kwargs))
    r.validate()
    r.freeze()
    return r


class NativeFirstDragonCostTests(unittest.TestCase):
    def game(self,hand=(DRAGON,DRAGON),*,board=(CARD,),enemy=(),enemy_hand=(),mana=40):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=(PLAIN,)*8,mana=mana,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(PLAIN,)*8,mana=40,max_mana=40,mana_cap=40)),seed=149),registry())

    def eid(self,g,cid,p=None,zone='hand'):
        s=g.state
        p=p or s.active_player
        return next(i for i in getattr(s.players[p],zone) if s.entities[i].card_id==cid)

    def play(self,g,cid,target=None):
        p=g.state.active_player
        eid=self.eid(g,cid)
        g.apply(PlayCard(p,eid,target_id=target,
            position=len(g.state.players[p].board) if g.state.entities[eid].kind==CardType.MINION else None))
        return eid

    def fact(self,g,cid=DRAGON,p=1):
        entity=g.state.entities[self.eid(g,cid,p)]
        return quote_input(g.state,g.registry,capture_cost_input(entity))

    def cost(self,g,cid=DRAGON,p=1):
        return self.fact(g,cid,p).amount

    def choose(self,g,key='ok'):
        q=g.state.pending_choice
        g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def portable(self,g):
        reader=registry(True)
        self.assertIsNot(reader,g.registry)
        saved=json.loads(json.dumps(g.snapshot()))
        other=Game.from_snapshot(saved,reader)
        for s in (other.snapshot(),g.clone().snapshot(),replay(build_replay(g),reader).snapshot()):
            self.assertEqual(canonical_hash(saved),canonical_hash(s))
        for p in (1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for private in ('tribal_inputs','contributions','first_play','resolution_frame','next_entity_id'):
                self.assertNotIn('"'+private+'"',public)
        return other

    def rehash(self,saved):
        saved['events_hash']=canonical_hash(saved['events'])
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        return saved

    def test_complete_pinned_actual_root_and_strict_bilingual_primary_faces(self):
        from tools.card_batch import check_face
        d=load_batch()
        self.assertEqual(len(d['cards']),1)
        self.assertEqual(len(d['official_observations']),2)
        raw=d['cards'][0]['record']
        for o in d['official_observations']:check_face(raw,o['face'],o['locale'])
        c=registry().card(CARD)
        self.assertEqual((c.cost,c.attack,c.health,c.metadata.tribes),(7,7,7,()))
        self.assertEqual(c.cost_auras,(AURA,))

    def test_only_first_current_dragon_costs_one_with_exact_actual_payment(self):
        g=self.game((PLAIN,DRAGON,DRAGON))
        self.assertEqual((self.cost(g,PLAIN),self.cost(g)),(4,1))
        self.play(g,PLAIN)
        self.assertEqual(self.cost(g),1)
        self.play(g,DRAGON)
        paid=g.state.play_history[-1].submitted_cost.quote
        self.assertEqual((paid.amount,g.state.players[1].mana,self.cost(g)),(1,35,5))
        fact=paid.contributions[0].first_play
        self.assertEqual((fact.tribes_any,len(fact.rows),len(fact.tribal_inputs)),(('dragon',),1,1))
        validate_cost_quote_fact(g.registry,paid)
        self.portable(g)

    def test_actual_current_hand_grant_spends_first_and_later_source_transform_cannot_erase_it(self):
        g=self.game((PLAIN,P+'tribe_dragon',P+'transform',DRAGON))
        original=self.eid(g,PLAIN)
        self.play(g,P+'tribe_dragon',original)
        self.assertEqual(self.cost(g,PLAIN),1)
        self.play(g,PLAIN)
        self.assertEqual(self.cost(g),5)
        self.play(g,P+'transform',original)
        self.assertEqual(self.cost(g),5)
        self.portable(g)

    def test_printed_dragon_stripped_before_submission_does_not_spend_first_dragon(self):
        g=self.game((DRAGON,P+'tribe_strip',DRAGON))
        original=self.eid(g,DRAGON)
        self.play(g,P+'tribe_strip',original)
        self.assertEqual(self.cost(g),5)
        self.play(g,DRAGON)
        self.assertEqual(self.cost(g),1)
        self.play(g,DRAGON)
        paid=g.state.play_history[-1].submitted_cost.quote
        self.assertEqual(paid.amount,1)
        self.assertEqual(len(paid.contributions[0].first_play.tribal_inputs[1].enchantments),1)
        self.portable(g)

    def test_later_board_tribe_change_does_not_rewrite_original_nonmatching_submission(self):
        g=self.game((PLAIN,P+'tribe_dragon',DRAGON))
        original=self.play(g,PLAIN)
        self.play(g,P+'tribe_dragon',original)
        self.assertEqual(self.cost(g),1)
        self.play(g,DRAGON)
        self.assertEqual(g.state.play_history[-1].cost,1)
        self.portable(g)

    def test_all_with_dragon_exclusion_and_fixed_one_even_for_printed_zero(self):
        g=self.game((ALL,P+'tribe_strip',FREE,DRAGON))
        original=self.eid(g,ALL)
        self.assertEqual((self.cost(g,ALL),self.cost(g,FREE)),(1,1))
        self.play(g,P+'tribe_strip',original)
        self.assertEqual(self.cost(g,ALL),6)
        self.play(g,ALL)
        self.assertEqual(self.cost(g,FREE),1)
        self.play(g,FREE)
        self.assertEqual(self.cost(g),5)
        self.portable(g)

    def test_source_from_hand_or_later_summon_never_resets_payer_qualification(self):
        g=self.game((CARD,DRAGON),board=())
        self.play(g,CARD)
        self.assertEqual(self.cost(g),1)
        self.portable(g)
        g=self.game((DRAGON,P+'summon',DRAGON),board=())
        self.play(g,DRAGON)
        self.play(g,P+'summon')
        self.assertEqual(self.cost(g),5)
        self.portable(g)

    def test_queries_generation_and_multiple_sources_have_no_separate_use_budget(self):
        g=self.game((DRAGON,DRAGON),board=(CARD,CARD))
        saved=g.snapshot()
        q=self.fact(g)
        generated=capture_generated_quote_fact(g.state,g.registry,1,DRAGON)
        self.assertEqual((q.amount,generated.amount),(1,1))
        self.assertEqual(len(q.contributions),2)
        self.assertEqual([c.first_play.is_first for c in q.contributions],[True,True])
        self.assertEqual(canonical_hash(saved),canonical_hash(g.snapshot()))
        self.play(g,DRAGON)
        self.assertEqual(self.cost(g),5)
        self.portable(g)

    def test_each_actual_turn_and_player_uses_its_own_first_dragon_history(self):
        g=self.game((DRAGON,DRAGON),enemy=(CARD,),enemy_hand=(DRAGON,DRAGON))
        self.play(g,DRAGON)
        self.assertEqual((self.cost(g),self.cost(g,p=2)),(5,1))
        g.apply(EndTurn(1))
        self.play(g,DRAGON)
        self.assertEqual(self.cost(g,p=2),5)
        g.apply(EndTurn(2))
        self.assertEqual(self.cost(g),1)
        self.portable(g)

    def test_source_lifetime_retirement_and_awaken_keep_original_history(self):
        for operation in ('silence','destroy','bounce','transform','sleep'):
            with self.subTest(operation=operation):
                g=self.game((P+operation,DRAGON))
                src=self.eid(g,CARD,zone='board')
                self.play(g,P+operation,src)
                self.assertEqual(self.cost(g),5)
                self.portable(g)
        g=self.game((P+'sleep',DRAGON,P+'wake',DRAGON))
        src=self.eid(g,CARD,zone='board')
        self.play(g,P+'sleep',src)
        self.play(g,DRAGON)
        self.play(g,P+'wake')
        self.assertEqual(self.cost(g),5)
        self.portable(g)

    def test_control_and_copy_affect_live_sources_without_moving_or_copying_history(self):
        g=self.game((P+'copy',P+'take',DRAGON),enemy_hand=(DRAGON,))
        src=self.eid(g,CARD,zone='board')
        self.play(g,P+'copy',src)
        self.play(g,DRAGON)
        self.play(g,P+'take',src)
        self.assertEqual(self.cost(g,DRAGON,p=2),1)
        self.portable(g)

    def test_pending_first_matching_submission_keeps_payment_and_next_card_not_first(self):
        g=self.game((PLAIN,WAIT,DRAGON))
        self.play(g,PLAIN)
        self.play(g,WAIT)
        self.assertEqual((g.state.play_history[-1].cost,self.cost(g)),(1,5))
        other=self.portable(g)
        self.choose(g,'silence')
        self.choose(other,'silence')
        self.assertEqual(g.state.play_history[-1].cost,1)
        self.assertEqual(canonical_hash(g.snapshot()),canonical_hash(other.snapshot()))
        self.portable(g)

    def test_root_and_choice_exception_preserve_qualification_payment_and_information(self):
        g=self.game((PLAIN,P+'failing',DRAGON))
        self.play(g,PLAIN)
        saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):self.play(g,P+'failing')
        self.assertEqual(canonical_hash(saved),canonical_hash(g.snapshot()))
        self.assertEqual(self.cost(g),1)
        self.portable(g)
        g=self.game((PLAIN,WAIT,DRAGON))
        self.play(g,PLAIN)
        self.play(g,WAIT)
        saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):self.choose(g,'bad')
        self.assertEqual(canonical_hash(saved),canonical_hash(g.snapshot()))
        self.assertEqual(self.cost(g),5)
        self.portable(g)

    def test_insufficient_second_payment_is_atomic_and_player_legal_quotes_agree(self):
        g=self.game(mana=1)
        first=self.eid(g,DRAGON)
        self.assertTrue(any(isinstance(a,PlayCard) and a.entity_id==first for a in g.legal_actions()))
        self.play(g,DRAGON)
        saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,DRAGON)
        self.assertEqual(canonical_hash(saved),canonical_hash(g.snapshot()))
        self.assertEqual(self.cost(g),5)
        self.portable(g)

    def test_unknown_original_eligible_tribes_are_explicit_but_unrelated_recipient_is_not_blocked(self):
        g=self.game((UNKNOWN,P+'summon',PLAIN),board=())
        self.play(g,UNKNOWN)
        self.play(g,P+'summon')
        self.assertEqual(self.cost(g,PLAIN),4)
        saved=g.snapshot()
        with self.assertRaisesRegex(UnsupportedDefinitionError,'originally submitted tribe'):
            capture_generated_quote_fact(g.state,g.registry,1,DRAGON)
        self.assertEqual(canonical_hash(saved),canonical_hash(g.snapshot()))
        self.portable(g)

    def test_rehashed_original_input_prefix_selector_and_missing_operands_reject(self):
        g=self.game((PLAIN,DRAGON))
        self.play(g,PLAIN)
        self.play(g,DRAGON)
        saved=g.snapshot()
        self.assertEqual(self.rehash(deepcopy(saved)),saved)
        for mutation in ('base_cost','truncate','selector','identity','missing'):
            bad=deepcopy(saved)
            contribution=bad['state']['play_history'][-1]['submitted_cost']['quote']['contributions'][0]
            first=contribution['first_play']
            if mutation=='base_cost':first['tribal_inputs'][0]['base_cost']+=1
            elif mutation=='truncate':first['tribal_inputs']=[]
            elif mutation=='selector':first['tribes_any']=['beast']
            elif mutation=='identity':first['tribal_inputs'][0]['card_id']=DRAGON
            else:del first['tribal_inputs']
            with self.subTest(mutation=mutation),self.assertRaises(SnapshotError):
                Game.from_snapshot(self.rehash(bad),registry(True))
        first=g.state.play_history[-1].submitted_cost.quote.contributions[0].first_play
        altered=replace(first,tribal_inputs=(replace(first.tribal_inputs[0],base_cost=99),))
        with self.assertRaisesRegex(ValueError,'original submitted'):
            validate_first_play_cost_prefix(g.state,g.registry,altered)
        self.portable(g)

    def test_strict_declaration_fact_binding_and_previous_format_rejection(self):
        for changes in ({'first_per_turn':True,'cost':CostSpec(set_to=1,card_types=(CardType.SPELL,))},
                {'first_per_turn':False},{'every_nth_per_turn':2},{'relation':'enemy'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(AURA,**changes)
        g=self.game((PLAIN,DRAGON))
        self.play(g,PLAIN)
        contribution=self.fact(g).contributions[0]
        with self.assertRaisesRegex(ValueError,'tribe qualifier'):
            replace(contribution,first_play=replace(contribution.first_play,tribes_any=('beast',)))
        saved=g.snapshot()
        self.assertEqual(saved['schema_version'],SNAPSHOT_SCHEMA_VERSION)
        saved['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(True))
        self.portable(g)


if __name__=='__main__':unittest.main()
