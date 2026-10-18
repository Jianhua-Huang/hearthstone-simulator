"""One complete Azure Fabled family: shared current Dragon condition and real casts."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.arcane_dragon_fabled_cards import QUEEN,KING,STONE,load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,CastSpell,DeckPolicy,DeckSpec,Game,
    MatchSetup,PlayerSetup,PlayCard,Rarity,Scenario,SelectChoice,SpellSchool,Zone,expand_fabled_cards)
from hs_sim.engine.effects import (ChoiceOption,CopyMinion,Destroy,GainArmor,InvokeBehavior,RequestChoice,Silence)
from hs_sim.engine.model import CostAuraSpec,CostSpec,TribeChangeSpec
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest

P='azure.fabled.test.';DRAGON,PLAIN,FILL=(P+x for x in ('dragon_body','plain_body','fill'))
ARC,FIRE,ONE,WAIT,AUTO,AUTOWAIT=(P+x for x in ('arcane','fire','one','wait','auto','auto_wait'))


@lru_cache(maxsize=None)
def registry(role):
    assert role in ('writer','reader')
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    for cid,tribes in ((DRAGON,('dragon',)),(PLAIN,()),(FILL,())):
        m=replace(meta,tribes=tribes,collectible=cid==FILL,max_copies=30 if cid==FILL else None)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=2,health=3,metadata=m))
    def spell(cid,body,cost=0,school=None,target=False):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid,spell_school=school,requires_target=target,metadata=meta))
    for cid,cost,school in ((ARC,3,SpellSchool.ARCANE),(FIRE,3,SpellSchool.FIRE),(ONE,1,SpellSchool.ARCANE)):
        spell(cid,lambda c:(GainArmor(c.player_id,2),),cost,school)
    def fail(c):raise ResolutionError('Azure deliberate choice failure')
    r.register_behavior(P+'fail',fail)
    def waiting(c):
        dragon=next((i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==DRAGON),None)
        effects=(GainArmor(c.player_id,2),*((Destroy(dragon,c.source_id),)if dragon is not None else()))
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',effects),
            ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),source_id=c.source_id),)
    spell(WAIT,waiting,3,SpellSchool.ARCANE)
    spell(AUTO,lambda c:(CastSpell(c.player_id,ARC,c.source_id),))
    spell(AUTOWAIT,lambda c:(CastSpell(c.player_id,WAIT,c.source_id,choices='player'),))
    spell(P+'auto_one',lambda c:(CastSpell(c.player_id,ONE,c.source_id),))
    for key,body in (('kill',lambda c:(Destroy(c.target_id,c.source_id),)),('silence',lambda c:(Silence(c.target_id),)),
        ('copy',lambda c:(CopyMinion(c.target_id,c.player_id),)),('sleep',lambda c:(MakeDormant(c.target_id,None),)),
        ('dragon',lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('dragon',)),c.source_id),)),
        ('plain',lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',()),c.source_id),))):
        spell(P+key,body,target=True)
    r.validate();r.freeze();return r


class ArcaneDragonFabledTests(unittest.TestCase):
    def game(self,hand=(ARC,),board=(QUEEN,DRAGON),enemy=()):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(FILL,)*5,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',board=enemy,deck=(FILL,)*5,mana=50,max_mana=50,mana_cap=50)),seed=228852),registry('writer'))
    def entity(self,g,cid,zone='board',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid=ARC,target=None):
        e=self.entity(g,cid,'hand');g.apply(PlayCard(1,e.id,target,position=len(g.state.players[1].board)if e.kind==CardType.MINION else None));return e.id
    def armor(self,g):return g.state.entities[g.state.players[1].hero_id].armor
    def select(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        r=registry('reader');self.assertIsNot(r,g.registry);self.assertEqual(r.fingerprint(),g.registry.fingerprint())
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,r)
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        for pid in (1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in ('resolution_frame','rng_state','NativeRepeatPlan','quote_input','SourceAllocationFact'):self.assertNotIn(key,public)
        return other
    def test_a00_queen_reduces_only_actual_arcane_spell_price(self):
        g=self.game(hand=(ARC,FIRE));self.play(g);self.play(g,FIRE)
        self.assertEqual((g.state.players[1].mana,self.armor(g)),(46,4));self.portable(g)
    def test_a01_king_repeats_paid_arcane_spell_once_with_one_payment(self):
        g=self.game(board=(KING,DRAGON));self.play(g)
        self.assertEqual((self.armor(g),g.state.players[1].mana,len(g.state.play_history)),(4,47,1));self.portable(g)
    def test_a02_king_repeats_automatic_arcane_without_an_unrelated_cost_query(self):
        g=self.game(hand=(AUTO,),board=(KING,DRAGON));self.play(g,AUTO)
        self.assertEqual((self.armor(g),g.state.players[1].mana),(4,50));self.assertEqual([x.origin for x in g.state.cast_history],['hand','effect','native_repeat']);self.portable(g)
    def test_a03_three_complete_sources_real_parent_links_and_reused_stone(self):
        d=load_batch();self.assertEqual([x['record']['id']for x in d['cards']],[QUEEN,KING])
        self.assertEqual([x['record']['id']for x in d['existing_dependencies']],[STONE])
        for row in (*d['cards'],*d['existing_dependencies']):self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        faces={o['card_id']:o['face']for o in d['official_observations']if o['locale']=='en_US'}
        self.assertEqual(set(faces[QUEEN]['childIds']),{faces[KING]['id'],faces[STONE]['id']})
        self.assertEqual(faces[KING]['parentId'],faces[QUEEN]['id']);self.assertEqual(faces[STONE]['parentId'],faces[QUEEN]['id'])
        self.assertEqual(registry('writer').card(STONE).on_play,'cards.simple_followup_p62.TIME_852t3')
    def test_b00_self_and_enemy_dragons_do_not_satisfy_another_friendly_dragon(self):
        for holder in (QUEEN,KING):
            with self.subTest(holder=holder):
                g=self.game(board=(holder,),enemy=(DRAGON,));self.play(g)
                self.assertEqual((self.armor(g),g.state.players[1].mana),(2,47))
    def test_b01_current_tribe_changes_enable_both_providers(self):
        for holder in (QUEEN,KING):
            with self.subTest(holder=holder):
                g=self.game(hand=(P+'dragon',ARC),board=(holder,PLAIN));self.play(g,P+'dragon',self.entity(g,PLAIN).id);self.play(g)
                self.assertEqual((self.armor(g),g.state.players[1].mana),(2,49)if holder==QUEEN else(4,47))
    def test_b02_removing_current_dragon_tribe_disables_both_providers(self):
        for holder in (QUEEN,KING):
            with self.subTest(holder=holder):
                g=self.game(hand=(P+'plain',ARC),board=(holder,DRAGON));self.play(g,P+'plain',self.entity(g,DRAGON).id);self.play(g)
                self.assertEqual((self.armor(g),g.state.players[1].mana),(2,47))
    def test_b03_controlled_dormant_dragon_counts_under_the_declared_profile(self):
        g=self.game(hand=(P+'sleep',ARC),board=(QUEEN,KING,DRAGON));self.play(g,P+'sleep',self.entity(g,DRAGON).id);self.play(g)
        self.assertEqual((self.armor(g),g.state.players[1].mana),(4,49))
    def test_b04_silence_source_removes_its_own_cost_or_repeat_effect(self):
        for holder in (QUEEN,KING):
            with self.subTest(holder=holder):
                g=self.game(hand=(P+'silence',ARC),board=(holder,DRAGON));self.play(g,P+'silence',self.entity(g,holder).id);self.play(g)
                self.assertEqual((self.armor(g),g.state.players[1].mana),(2,47))
    def test_c00_queen_and_king_share_each_other_as_witnesses(self):
        g=self.game(board=(QUEEN,KING));self.play(g);self.assertEqual((self.armor(g),g.state.players[1].mana),(4,49))
    def test_c01_niri_and_king_share_one_automatic_twice_plan(self):
        g=self.game(hand=(P+'auto_one',),board=('TLC_836',KING,DRAGON));self.play(g,P+'auto_one')
        self.assertEqual(self.armor(g),4);self.assertEqual(len([x for x in g.state.cast_history if x.card_id==ONE]),2);self.portable(g)
    def test_c02_accepted_automatic_witness_survives_death_during_original_choice(self):
        g=self.game(hand=(AUTOWAIT,),board=(KING,DRAGON));self.play(g,AUTOWAIT);other=self.portable(g);snap=g.snapshot()
        work=next(x for x in g._frame.continuation if type(x).__name__=='RepeatAutomaticSpell');self.assertIsNone(work.plan.cost)
        with self.assertRaises(ResolutionError):self.select(g,'fail')
        self.assertEqual(g.snapshot(),snap)
        for game in (g,other):self.select(game);self.assertIsNotNone(game.state.pending_choice);self.select(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.armor(g),4);self.portable(g)
    def test_c03_paid_repeat_keeps_original_dragon_acceptance_after_witness_dies(self):
        g=self.game(hand=(WAIT,),board=(KING,DRAGON));self.play(g,WAIT);self.select(g);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g);self.select(g);self.assertEqual((self.armor(g),g.state.players[1].mana),(4,47))
    def test_c04_current_copy_receives_an_independent_native_arcane_source(self):
        g=self.game(hand=(P+'copy',ARC),board=(QUEEN,DRAGON));self.play(g,P+'copy',self.entity(g,QUEEN).id)
        self.play(g);self.assertEqual((self.armor(g),g.state.players[1].mana),(2,50));self.portable(g)
    def test_d00_reused_stone_resurrects_current_dragon_at_death_with_fresh_bodies(self):
        g=self.game(hand=(P+'dragon',P+'kill',P+'kill',STONE),board=(DRAGON,PLAIN));old=self.entity(g,DRAGON).id;changed=self.entity(g,PLAIN).id
        self.play(g,P+'dragon',changed);self.play(g,P+'kill',old);self.play(g,P+'kill',changed);self.play(g,STONE)
        board=[g.state.entities[i]for i in g.state.players[1].board];self.assertEqual([x.card_id for x in board],[DRAGON,PLAIN])
        self.assertTrue(all(x.id not in(old,changed)for x in board));self.assertEqual(g.state.players[1].mana,42);self.portable(g)
    def test_d01_reused_stone_excludes_a_dragon_that_lost_its_tribe_before_death(self):
        g=self.game(hand=(P+'plain',P+'kill',STONE),board=(DRAGON,));eid=self.entity(g,DRAGON).id
        self.play(g,P+'plain',eid);self.play(g,P+'kill',eid);self.play(g,STONE);self.assertFalse(g.state.players[1].board)
    def test_d02_reused_stone_empty_history_has_no_rng(self):
        g=self.game(hand=(STONE,),board=());rng=g._rng.getstate();self.play(g,STONE);self.assertFalse(g.state.players[1].board);self.assertEqual(g._rng.getstate(),rng)
    def test_e00_real_fabled_bundle_is_thirty_original_cards_and_uses_normal_mulligans(self):
        r=registry('writer');cards=expand_fabled_cards((QUEEN,)+(FILL,)*27,r);self.assertEqual(cards[:3],(QUEEN,KING,STONE));self.assertEqual(len(cards),30)
        own=DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,cards);other=DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,(FILL,)*30)
        policy=DeckPolicy('K228-fixture','K228-fixed','experimental',tuple(r.cards))
        g=Game.from_decks(MatchSetup((own,other),policy,'GAME_005',228852,1),r)
        self.assertEqual(g.state.players[1].original_deck,cards);self.portable(g)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        self.assertEqual(g.state.players[1].original_deck,cards);self.portable(g)
    def test_e01_generated_root_does_not_add_original_fabled_companions(self):
        g=self.game(hand=(QUEEN,),board=());self.play(g,QUEEN)
        self.assertFalse(g.state.players[1].hand);self.assertFalse(any(g.state.entities[i].card_id in(KING,STONE)for i in g.state.players[1].deck))
    def test_e02_native_arcane_relation_rejects_unreviewed_numeric_or_type_combinations(self):
        for spec in (CostSpec(delta=-1,card_types=(CardType.SPELL,)),CostSpec(delta=-2),CostSpec(set_to=0,card_types=(CardType.SPELL,))):
            with self.assertRaises(ValueError):CostAuraSpec(spec,relation='friendly_arcane_spells')
