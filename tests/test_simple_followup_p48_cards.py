"""Grouped native consumers, actual public gaps and independent portable boundaries."""
from dataclasses import asdict,replace
from functools import lru_cache
import json,random,re,unittest
from unittest.mock import patch
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p48_cards import (MOONKIN,TRUTH,CONSTRUCT,SHELL,OVERHEAT,
    SPELLCASTER,TOLVIR,HARBINGER,ROOTS,SKIPPED,EXISTING_DEPENDENCIES,POOL_ID,load_batch,register_simple_followup_p48_cards)
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,Game,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,EndTurn,TargetMode,TargetSpec,Zone)
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.damage_history import spell_damage_dealt
from hs_sim.engine.effects import (AddCostModifier,AddToHand,Buff,ChangeControl,ChoiceOption,Damage,Destroy,Draw,
    GainArmor,GrantKeyword,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.limited_triggers import GrantLimitedTrigger
from hs_sim.engine.model import (CostSpec,DamageKind,EndTurnSpec,LimitedTriggerSpec,QuestSpec,
    QuestStageSpec,Rarity,RewindSpec)
from hs_sim.engine.player_target_inputs import PlayerTargetRuleSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.quests import RemoveQuest
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import BuffCapturedMinion,DestroyCapturedMinion,GrantCapturedKeyword,MinionReference
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference,DiscardMatching,ModifyStoredCost
from hs_sim.targets import canonical_digest

TEST='p48.test.';YETI='CORE_CS2_182';TWO='CORE_GVG_085';SIX='CORE_BAR_310';NATURE='CORE_CS2_009'
MEMBERS=(TWO,);CONTEXT=GenerationContext('p48-explicit-complete-fixture','experimental')
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    present=tuple(i in r.cards for i in ROOTS)
    if not any(present):register_simple_followup_p48_cards(r)
    elif not all(present):raise AssertionError('P48 central assembly must contain the full supported batch')
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for i in members:
        if i not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(i)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p48-explicit-complete-v1',CONTEXT.target_id,
        CONTEXT.mode,tuple(PoolMember(i)for i in members),complete=True))
    def prices(c,amount):
        return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(set_to=amount),c.source_id)
            for p in(1,2)for i in c.state.players[p].hand)
    def ceremony_probe(c):
        # Deliberate public-primitive counterexample, never a DINO_417 adapter.
        refs=tuple(MinionReference.capture(c.state.entities[i])for i in c.state.players[1].board
            if c.state.entities[i].card_id in(YETI,TWO))
        spec=LimitedTriggerSpec('turn_ended',TEST+'due',condition_id=TEST+'owner',end_turn=EndTurnSpec())
        return tuple(e for ref in refs for e in(BuffCapturedMinion(ref,1,0,c.source_id),
            GrantCapturedKeyword(ref,Keyword.RUSH,c.source_id),
            GrantLimitedTrigger(ref.entity_id,spec,c.source_id,expires_turn=c.state.turn)))
    scripts={'damage':lambda c:(Damage(c.state.players[3-c.player_id].hero_id,1,c.source_id,DamageKind.SPELL),),
        'zero':lambda c:(Damage(c.state.players[2].hero_id,0,c.source_id,DamageKind.SPELL),),
        'enemy':lambda c:(CastSpell(2,TEST+'damage',c.source_id),),
        'discount':lambda c:prices(c,1),'free':lambda c:prices(c,0),
        'aura':lambda c:(AddCostModifier(1,CostSpec(delta=2,card_types=(CardType.MINION,)),source_id=c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),'buff':lambda c:(Buff(c.target_id,3,4,c.source_id),),
        'transform':lambda c:(Transform(c.target_id,'CORE_CS2_231'),),
        'natural':lambda c:(Summon(1,HARBINGER),),'add':lambda c:(AddToHand(1,HARBINGER,c.source_id),),
        'draw':lambda c:(Draw(1,source_id=c.source_id),),'one_summon':lambda c:(Summon(1,TEST+'one'),),
        'reenter':lambda c:(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),1,cause=SummonCause.capture(c)),),
        'ceremony_probe':ceremony_probe,
        'due':lambda c:(DestroyCapturedMinion(MinionReference.capture(c.source),c.trigger.source_id),),
        'remove_quest':lambda c:tuple(RemoveQuest(i)for i in c.state.players[1].quests),
        'fail':lambda c:(_ for _ in()).throw(ResolutionError('P48 deliberate continuation failure')),
        'noop':lambda c:(),
        'rewind_damage':lambda c:()if c.rewind_attempt else(Damage(c.state.players[2].hero_id,1,c.source_id,DamageKind.SPELL),)}
    targeted={'bounce','kill','silence','buff','transform'}
    for name,body in scripts.items():
        r.register_behavior(TEST+name,body)
        kwargs=dict(targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)))if name in targeted else{}
        if name=='rewind_damage':kwargs.update(keywords=(Keyword.REWIND,),rewind=RewindSpec())
        r.register_card(CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,metadata=META,**kwargs))
    r.register_trigger_condition(TEST+'owner',lambda c:c.event.player_id==1)
    r.register_card(CardDefinition(TEST+'one','One-cost battlecry witness',CardType.MINION,cost=1,attack=1,health=1,
        battlecry=TEST+'one_armor',metadata=META));r.register_behavior(TEST+'one_armor',lambda c:(GainArmor(1,1),))
    r.register_card(CardDefinition(TEST+'ability','Minion ability witness',CardType.MINION,health=3,
        battlecry=TEST+'ability_damage',metadata=META));r.register_behavior(TEST+'ability_damage',
        lambda c:(Damage(c.state.players[2].hero_id,1,c.source_id,DamageKind.MINION_ABILITY),))
    quest=TEST+'quest';r.register_card(CardDefinition(quest,'Quest witness',CardType.SPELL,
        keywords=(Keyword.QUEST,),quest=QuestSpec('quest',(QuestStageSpec(quest,99,('minion_summoned',),TEST+'noop',TEST+'noop'),)),
        metadata=replace(META,collectible=True,rarity=Rarity.LEGENDARY)))
    def public_quest(c):
        own=next(p for p in c.observation['players']if p['id']==c.player_id)
        if 'quests_played_total'not in own:raise UnsupportedDefinitionError('Complete Quest-play fact absent from public target DTO')
        return own['quests_played_total']>0
    r.register_player_target_rule(PlayerTargetRuleSpec(TEST+'quest_rule','v1'),public_quest)
    r.register_card(CardDefinition(TEST+'quest_probe','Public target capability probe',CardType.MINION,health=1,
        battlecry=TEST+'noop',target_rule=TEST+'quest_rule',targeting=TargetSpec(TargetMode.IF_AVAILABLE,
        zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy'),metadata=META))
    if mode:
        def eligible(c):
            e=c.event
            if mode=='cost':return e.source_id is not None and c.state.entities[e.source_id].card_id==TRUTH
            if mode=='reentry':return e.target_id is not None and c.state.entities[e.target_id].card_id==YETI
            if mode in('discard','armor'):return e.player_id==1
            if mode=='copy_buff':return e.target_id is not None and c.state.entities[e.target_id].card_id==SPELLCASTER
            return any(root.request.cause.source.card_id==HARBINGER and any(d.outcome=='delivered'and d.entity.entity_id==e.target_id for d in root.deliveries)for root in c.state.card_summon_history)
        def watch(c):
            if mode=='copy_buff':return(Buff(c.event.target_id,3,4,c.source_id),)
            if mode=='reentry':
                target=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==TWO)
                return(ReturnToHand(target),InvokeBehavior(TEST+'reenter',c.source_id,1,target))
            return(RequestChoice(1,(ChoiceOption('ok','Continue',(GainArmor(1,10),)if mode=='armor'else()),ChoiceOption('bad','Fail',
                (InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        event={'cost':'cost_modified','reentry':'stats_changed','discard':'card_discarded','armor':'armor_lost'}.get(mode,'minion_summoned')
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','Ordinary reaction witness',CardType.MINION,health=9,metadata=META,
            limited_triggers=(LimitedTriggerSpec(event,TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

@lru_cache(maxsize=None)
def shared_registry(members,mode,pool):return registry(members,mode,pool)

class SimpleFollowupP48Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),deck=(YETI,)*10,enemy_hand=(),members=MEMBERS,mode=None,
            pool=True,context=CONTEXT,armor=0):
        self.config=(members,mode,pool)
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,armor=armor,
            mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*10,
            mana=50,max_mana=50,mana_cap=50)),seed=4848,generation_context=context),shared_registry(*self.config))
    def first(self,g,cid,zone='hand',p=1):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        e=self.first(g,cid);g.apply(PlayCard(1,e.id,target,position=len(g.state.players[1].board)if e.kind==CardType.MINION else None));return e.id
    def choose(self,g,key='ok'):g.apply(SelectChoice(1,g.state.pending_choice.id,(key,)))
    def ids(self,g,zone='board',p=1):return[g.state.entities[i].card_id for i in getattr(g.state.players[p],zone)]
    def price(self,g,i):return quote_unselected_cost(g.state,g.registry,g.state.entities[i]).amount
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(*self.config))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for k in('rng_state','resolution_frame','pool_id','behavior_id','damage_history','hand_entries'):
                self.assertNotIn('"'+k+'"',public)
        return other

    def test_complete_rows_twenty_faces_full_wisp_family_pins_and_null_limits(self):
        d=load_batch();r=batch_registry();self.assertEqual((len(d['cards']),len(d['skipped']),len(d['existing_dependencies']),len(d['official_observations'])),(8,2,2,20))
        norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$#&_]','',s)
        for row in d['cards']+d['skipped']:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            for o in(o for o in d['official_observations']if o['card_id']==raw['id']):
                f=o['face'];en=o['locale']=='en_US';self.assertEqual((f['id'],f['manaCost']),(raw['dbf_id'],raw['cost']))
                self.assertEqual(f['name'],raw['name_en'if en else'name']);text=raw['text_en'if en else'text'];text=text.replace('@','')if raw['id']==MOONKIN else text
                self.assertEqual(norm(f['text']),norm(text))
                self.assertFalse(re.match(r'^[A-Za-z]:',o['response_file']))
            if raw['id']in ROOTS:
                c=r.card(raw['id']);self.assertEqual(c.metadata,metadata_from_record(raw));self.assertEqual(c.cost,raw['cost'])
                self.assertEqual(c.spell_school.value if c.spell_school else None,row['spell_school'])
        for row in d['existing_dependencies']:
            self.assertIsNone(row['record']['cost']);self.assertEqual(canonical_digest(asdict(r.card(row['record']['id']))),row['definition_sha256'])
            self.assertEqual(row['definition']['cost'],0)
        wisps=[x['record']['id']for x in d['wisp_identity_evidence']];self.assertEqual(len(wisps),7)
        self.assertIn('GILA_BOSS_55t',wisps);self.assertNotIn('GILA_BOSS_55t',r.cards)
        self.assertTrue(all(x['record']['tags']['3881']==1 for x in d['wisp_identity_evidence']))
        self.assertFalse(d['scope']['cn_calibrated']);self.assertFalse(d['scope']['formal_pool_complete'])

    def test_existing_complete_definitions_pool_rows_defaults_and_main_judgment_fix_preserved(self):
        with patch('hs_sim.cards.simple_followup_p48_cards.register_simple_followup_p48_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS))
        for i,c in before.cards.items():self.assertEqual(asdict(c),asdict(after.card(i)))
        self.assertEqual(dict(before.pool_cards),dict(after.pool_cards));self.assertEqual(dict(before.pools),dict(after.pools))
        self.assertEqual(dict(before.generation_families),dict(after.generation_families))
        from hs_sim.engine.representative import build_registry as default
        self.assertEqual(default().fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_moonkin_owner_end_base_one_plus_current_living_controlled_wisps(self):
        for board,expected in(((MOONKIN,),1),((MOONKIN,'CORE_CS2_231','EDR_851t'),3)):
            with self.subTest(board=board):
                g=self.game(board=board,enemy=('CORE_CS2_231',),pool=False,context=None);g.apply(EndTurn(1))
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,expected);g.apply(EndTurn(2))
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,expected)
        g=self.game((TEST+'transform',TEST+'silence'),board=(MOONKIN,YETI),pool=False,context=None)
        self.play(g,TEST+'transform',self.first(g,YETI,'board').id);self.play(g,TEST+'silence',self.first(g,'CORE_CS2_231','board').id)
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)

    def test_truth_current_printed_prices_both_original_physical_hands_and_opponent_privacy(self):
        g=self.game((TEST+'discount',TRUTH,YETI),enemy_hand=(SIX,TWO),pool=False,context=None)
        self.play(g,TEST+'discount');own=self.first(g,YETI).id;enemy=g.state.players[2].hand[:]
        self.assertEqual([self.price(g,i)for i in(own,*enemy)],[1,1,1]);self.play(g,TRUTH)
        self.assertEqual([self.price(g,i)for i in(own,*enemy)],[4,6,2])
        public=json.dumps(g.for_player(1).observe())+json.dumps(g.player_events(1))
        for cid in(SIX,TWO):self.assertNotIn('"'+cid+'"',public)

        g=self.game((TEST+'discount',TEST+'aura',TRUTH,YETI),enemy_hand=(SIX,),pool=False,context=None)
        self.play(g,TEST+'discount');self.play(g,TEST+'aura');self.play(g,TRUTH)
        self.assertEqual(self.price(g,self.first(g,YETI).id),6);self.assertEqual(self.price(g,g.state.players[2].hand[0]),6)

    def test_truth_mid_cost_wait_restores_replays_and_failed_resume_keeps_original_queue(self):
        g=self.game((TEST+'discount',TRUTH,YETI),enemy_hand=(SIX,),mode='cost',pool=False,context=None)
        self.play(g,TEST+'discount');self.play(g,TRUTH);other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.price(g,g.state.players[2].hand[0]),6)

    def test_construct_original_excess_normal_draw_burn_shield_and_no_target(self):
        for target,expected in((TEST+'one',4),(YETI,0),(TWO,0)):
            with self.subTest(target=target):
                g=self.game((CONSTRUCT,),enemy=(target,),pool=False,context=None);self.play(g,CONSTRUCT,self.first(g,target,'board',2).id)
                self.assertEqual(len(g.state.draw_history),expected)
                result=next(r.health_result for r in g.state.damage_history if r.health_result.source_card_id==CONSTRUCT)
                self.assertEqual(result.base_amount,5);self.assertEqual(result.spell_bonus,0)
        g=self.game((CONSTRUCT,)+(YETI,)*9,enemy=(TEST+'one',),pool=False,context=None)
        self.play(g,CONSTRUCT,self.first(g,TEST+'one','board',2).id);self.assertEqual(len(g.state.players[1].hand),10)
        self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),3)
        g=self.game((CONSTRUCT,),pool=False,context=None);self.play(g,CONSTRUCT);self.assertFalse(g.state.draw_history)

    def test_shell_spends_actual_up_to_five_and_uses_distinct_spell_pulses(self):
        for armor in(0,1,3,8):
            with self.subTest(armor=armor):
                g=self.game((SHELL,),board=(YETI,),enemy=(YETI,),armor=armor,pool=False,context=None);self.play(g,SHELL)
                spent=min(5,armor);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,armor-spent)
                rows=[r.health_result for r in g.state.damage_history if r.health_result.source_card_id==SHELL]
                self.assertEqual(len(rows),2*spent);self.assertTrue(all(r.base_amount==1 for r in rows))
                self.assertEqual(len([e for e in g.events if e.kind=='armor_loss_resolved']),1)
        g=self.game((SHELL,),enemy=(TWO,),armor=2,pool=False,context=None);target=self.first(g,TWO,'board',2).id;self.play(g,SHELL)
        self.assertEqual(g.state.entities[target].health,1);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[target].keywords)
        g=self.game((SHELL,),board=('CORE_EX1_012',),enemy=(YETI,),armor=1,pool=False,context=None);target=self.first(g,YETI,'board',2).id
        self.play(g,SHELL);self.assertEqual(g.state.entities[target].health,3)

    def test_shell_original_actual_armor_result_survives_wait_and_later_balance_change(self):
        g=self.game((SHELL,),board=(YETI,),enemy=(YETI,),armor=2,mode='armor',pool=False,context=None)
        self.play(g,SHELL);self.assertIsNotNone(g.state.pending_choice);self.assertFalse(g.state.damage_history)
        other=self.portable(g)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,10)
        self.assertEqual(self.first(g,YETI,'board',2).health,3)

    def test_overheat_only_successful_random_nature_discard_gives_same_originals_second_buff(self):
        for extra,stats in(((),(5,6)),((NATURE,),(6,7))):
            with self.subTest(extra=extra):
                g=self.game((OVERHEAT,*extra),board=(YETI,),enemy=(YETI,),pool=False,context=None);self.play(g,OVERHEAT)
                e=self.first(g,YETI,'board');self.assertEqual((e.attack,e.health),stats)
                self.assertEqual((self.first(g,YETI,'board',2).attack,self.first(g,YETI,'board',2).health),(4,5))
                self.assertEqual(len(g.state.discard_history),len(extra))

    def test_overheat_original_group_does_not_buff_same_id_reentry_after_first_reaction(self):
        g=self.game((OVERHEAT,NATURE),board=(YETI,TWO),mode='reentry',pool=False,context=None)
        old=self.first(g,TWO,'board');self.play(g,OVERHEAT);current=g.state.entities[old.id]
        self.assertNotEqual(current.board_presence_id,old.board_presence_id);self.assertEqual((current.attack,current.health),(1,2))
        self.assertEqual((self.first(g,YETI,'board').attack,self.first(g,YETI,'board').health),(6,7))

    def test_overheat_real_discard_wait_restore_and_replay_keeps_original_success_followup(self):
        g=self.game((OVERHEAT,NATURE),board=(YETI,),mode='discard',pool=False,context=None);self.play(g,OVERHEAT)
        other=self.portable(g);self.assertEqual(self.first(g,YETI,'board').attack,5)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.first(g,YETI,'board').attack,6)

    def test_spellcaster_actual_own_spell_damage_current_turn_copy_has_no_battlecry(self):
        g=self.game((TEST+'damage',SPELLCASTER,TEST+'buff'));self.play(g,TEST+'damage');self.play(g,SPELLCASTER)
        self.assertEqual(self.ids(g).count(SPELLCASTER),2);self.assertEqual(len(g.state.battlecry_history),1)
        self.assertEqual(spell_damage_dealt(g.state,g.registry,1,turn=g.state.turn),1)
        for prefix in(TEST+'zero',TEST+'enemy',TEST+'ability'):
            with self.subTest(prefix=prefix):
                g=self.game((prefix,SPELLCASTER));self.play(g,prefix);self.play(g,SPELLCASTER)
                self.assertEqual(self.ids(g).count(SPELLCASTER),1)

    def test_spellcaster_copies_current_buffed_original_residence_after_arrival_reaction(self):
        g=self.game((TEST+'damage',SPELLCASTER),mode='copy_buff');self.play(g,TEST+'damage');self.play(g,SPELLCASTER)
        bodies=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==SPELLCASTER]
        self.assertEqual(len(bodies),2);self.assertTrue(all((e.attack,e.health)==(5,9)for e in bodies))

    def test_spellcaster_does_not_count_discarded_rewind_attempt_damage_or_prior_turn(self):
        g=self.game((TEST+'rewind_damage',SPELLCASTER));self.play(g,TEST+'rewind_damage');self.choose(g,'retry')
        self.assertEqual(spell_damage_dealt(g.state,g.registry,1,turn=g.state.turn),0);self.play(g,SPELLCASTER)
        self.assertEqual(self.ids(g).count(SPELLCASTER),1)
        g=self.game((TEST+'damage',SPELLCASTER));self.play(g,TEST+'damage');g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,SPELLCASTER)
        self.assertEqual(self.ids(g).count(SPELLCASTER),1)

    def test_tolvir_uses_printed_committed_one_cost_duplicates_unpaid_and_no_battlecry(self):
        g=self.game((TEST+'free',TEST+'one',TEST+'one',TWO,TOLVIR,TEST+'one_summon'))
        self.play(g,TEST+'free');self.play(g,TEST+'one');self.play(g,TEST+'one');self.play(g,TWO);self.play(g,TEST+'one_summon')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.play(g,TOLVIR)
        self.assertEqual(self.ids(g).count(TEST+'one'),5);self.assertEqual(self.ids(g).count(TWO),1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)
        self.assertEqual([p.cost for p in g.state.play_history if p.card_id==TEST+'one'],[0,0])

    def test_harbinger_only_own_real_battlefield_to_hand_repeated_returns_not_generation_or_draw(self):
        g=self.game((TEST+'bounce',TEST+'bounce'),board=(HARBINGER,));source=self.first(g,HARBINGER,'board').id
        self.play(g,TEST+'bounce',source);self.assertEqual(self.ids(g).count(TWO),2);self.play(g,HARBINGER);self.play(g,TEST+'bounce',source)
        self.assertEqual(self.ids(g).count(TWO),4);self.assertEqual(g.state.entities[source].zone,Zone.HAND)
        for hand,deck in(((TEST+'add',),()),((TEST+'draw',),(HARBINGER,)),((TEST+'natural',),())):
            g=self.game(hand,deck=deck);self.play(g,hand[0]);self.assertEqual(self.ids(g).count(TWO),0)

    def test_harbinger_first_random_arrival_wait_restore_bad_resume_and_once_completion(self):
        g=self.game((TEST+'bounce',),board=(HARBINGER,),mode='summon');source=self.first(g,HARBINGER,'board').id
        self.play(g,TEST+'bounce',source);other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.ids(g).count(TWO),2)

    def test_harbinger_unknown_complete_two_cost_pool_fails_before_random_and_return_rolls_back(self):
        r=batch_registry();unknown=next(c.card_id for c in r.pool_cards.values()if c.kind==CardType.MINION
            and c.cost==2 and c.metadata.collectible and c.card_id not in r.cards)
        g=self.game((TEST+'bounce',),board=(HARBINGER,),members=(TWO,unknown));saved=g.snapshot();calls=[];original=random.Random.randrange
        def spy(r,*a,**kw):calls.append(a);return original(r,*a,**kw)
        with patch.object(random.Random,'randrange',autospec=True,side_effect=spy):
            with self.assertRaises(ResolutionError):self.play(g,TEST+'bounce',self.first(g,HARBINGER,'board').id)
        self.assertFalse(calls);self.assertEqual(g.snapshot(),saved)

    def test_real_ceremony_primitive_probe_rebinds_bare_trigger_to_same_id_new_residence(self):
        g=self.game((TEST+'ceremony_probe',),board=(YETI,TWO),mode='reentry',pool=False,context=None)
        old=self.first(g,TWO,'board');presence=old.board_presence_id;self.play(g,TEST+'ceremony_probe')
        current=g.state.entities[old.id];self.assertNotEqual(current.board_presence_id,presence)
        self.assertEqual((current.attack,current.health),(1,2));self.assertNotIn(Keyword.RUSH,current.keywords)
        self.assertTrue(any(a.kind=='limited_trigger'and a.limited_trigger.behavior_id==TEST+'due'for a in current.abilities))
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[old.id].zone,Zone.GRAVEYARD)
        self.assertNotIn('DINO_417',g.registry.cards)

    def test_real_quest_history_target_probe_cannot_read_required_fact_from_public_context(self):
        g=self.game((TEST+'quest',TEST+'remove_quest',TEST+'quest_probe'),enemy=(YETI,),pool=False,context=None)
        self.play(g,TEST+'quest');self.play(g,TEST+'remove_quest');own=next(p for p in g.for_player(1).observe()['observation']['players']if p['id']==1)
        self.assertEqual(own['quests'],[]);self.assertTrue(any(p.card_id==TEST+'quest'for p in g.state.play_history))
        self.assertNotIn('quests_played_total',own);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Quest-play fact absent'):
            self.play(g,TEST+'quest_probe',self.first(g,YETI,'board',2).id)
        self.assertEqual(g.snapshot(),saved);self.assertNotIn('TLC_987',g.registry.cards)

if __name__=='__main__':unittest.main()
