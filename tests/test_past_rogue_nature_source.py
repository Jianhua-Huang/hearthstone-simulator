"""Real Rogue Nature spell entries, weapon residence and original draw-copy."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import past_rogue_nature_source as native
from hs_sim.cards.simple_followup_p89_cards import WO,NATURE_PAST_POOL,QUERIES
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayCard,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (ChoiceOption,Damage,Draw,EquipWeapon,GainArmor,InvokeBehavior,
    RandomDamage,RequestChoice)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CardClass,CardDefinition,CardType,CostSpec,Keyword,TriggerSpec,Zone
from hs_sim.engine.physical_draw_groups import DrawGroupReward
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.zones import CardReference,ModifyStoredCost,MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError,canonical_digest

P='k666.'
A,B,W,W2,LAST,HIGH,HURT,PREP,FAIL,WDRAW,WBUFF,WATTACK=(P+x for x in
    ('plain','alternate','weapon','replacement','last-weapon','higher','hurt','prepare','fail','draw-watch','buff-watch','attack-watch'))
WARS=(P+'war-a',P+'war-b',P+'war-c')
MAGE=P+'mage-only';CTX=GenerationContext(P+'reference','experimental')


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=opening_registry();native.register_past_rogue_nature_cards(r)
    for cid,attack,health in ((A,0,8),(B,2,9)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=2,attack=attack,health=health,metadata=metadata()))
    for cid,attack,durability in ((W,2,2),(W2,1,4),(LAST,2,1)):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,cost=1,attack=attack,durability=durability,metadata=metadata()))
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ResolutionError('K666 deliberate rollback')))
    r.register_behavior(HIGH,lambda c:())
    r.register_behavior(HURT,lambda c:(Damage(c.state.players[c.player_id].hero_id,9,c.source_id),))
    def prepare(c):
        ref=CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[0]])
        return(BuffStoredCard(ref,2,3,c.source_id),ModifyStoredCost(ref,CostSpec(set_to=0),c.source_id))
    r.register_behavior(PREP,prepare)
    for cid,cost in ((HIGH,3),(HURT,0),(PREP,0)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid,metadata=metadata(collectible=False)))
    def fault(c):return(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))
    def watch(c,kind):
        source=c.state.entities.get(c.event.source_id)
        if source is None:return()
        if kind=='draw':
            if source.card_id!='UNG_060':return()
            ref=CardReference.capture(c.state.entities[c.event.target_id])
            options=(ChoiceOption('continue','Continue'),ChoiceOption('transform','Transform drawn card',(TransformStoredCard(ref,B),)),
                ChoiceOption('interleave','Return and draw another',(MoveCard(ref,c.player_id,Zone.DECK,position='bottom',source_id=c.source_id),Draw(c.player_id,1,c.source_id))),
                ChoiceOption('fault','Fail',fault(c)))
        elif kind=='buff':
            if source.card_id!='YOP_015t':return()
            options=(ChoiceOption('continue','Continue'),ChoiceOption('replace','Replace weapon',(EquipWeapon(c.player_id,W2),)),ChoiceOption('fault','Fail',fault(c)))
        else:
            if source.kind!=CardType.HERO or c.event.source_id!=c.state.players[c.player_id].hero_id:return()
            options=(ChoiceOption('continue','Continue'),ChoiceOption('replace','Replace weapon',(EquipWeapon(c.player_id,W2),)),ChoiceOption('fault','Fail',fault(c)))
        return(RequestChoice(c.player_id,options,c.source_id),)
    for cid,kind,event in ((WDRAW,'draw','card_drawn'),(WBUFF,'buff','stats_changed'),(WATTACK,'attack','attack_finished')):
        r.register_behavior(cid,lambda c,kind=kind:watch(c,kind))
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=20,triggers=(TriggerSpec(event,cid),),metadata=metadata(collectible=False)))
    r.register_behavior(P+'armor',lambda c:(GainArmor(c.player_id,1),))
    for cid in WARS+(MAGE,):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=P+'armor',metadata=metadata(CardClass.MAGE if cid==MAGE else CardClass.WARRIOR)))
    members=WARS+(MAGE,A)
    for cid in members:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition('constructed.cards',P+'complete',CTX.target_id,CTX.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    r.validate();return r


class RogueNatureSourceTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),enemy=(),weapon=None,enemy_weapon=None,other_hand=(),deck=(A,)*12,other_deck=(B,)*12,watch=None):
        self.mode='small'
        board=board+(({'draw':WDRAW,'buff':WBUFF,'attack':WATTACK}[watch],)if watch else())
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,weapon_card_id=weapon,deck=deck,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',hand=other_hand,board=enemy,weapon_card_id=enemy_weapon,deck=other_deck,mana=10,max_mana=10)),seed=666,generation_context=CTX),
            fixture())

    def actual(self,*,hero='HERO_03',seed=666):
        self.mode='host';h=host();deck=('CORE_EX1_169',)*20
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=('CORE_EX1_169',),board=(WO,),deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=deck,mana=10,max_mana=10)),seed=seed,generation_context=h.context),h.registry)

    def ids(self,g,zone='hand',player=1):return[g.state.entities[i].card_id for i in getattr(g.state.players[player],zone)]
    def hero(self,g,player=1):return g.state.entities[g.state.players[player].hero_id]
    def weapon(self,g,player=1):return g.state.entities[g.state.players[player].weapon_id]
    def attack(self,g,target=None):g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id if target is None else target))
    def next_turn(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def finish(self,g):
        for _ in range(20):
            q=g.state.pending_choice
            if q is None:return
            self.choose(g,'continue'if any(o.id=='continue'for o in q.options)else q.options[0].id)
        self.fail('Unbounded real source continuation')

    def test_full_original_faces_roles_dependencies_and_native_pins(self):
        d=native.load_batch();h=host();native.checked_native(h.registry,d)
        self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['evidence_only']),len(d['official_observations'])),(9,2,6,24))
        for key in ('cards','dependencies','existing_dependencies','evidence_only'):
            for row in d[key]:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        for row in d['cards']+d['dependencies']:
            self.assertEqual(canonical_digest(asdict(h.registry.card(row['record']['id']))),row['definition_sha256'])
        for cid in native.ROOTS:self.assertTrue(h.registry.card(cid).metadata.collectible)
        for cid in native.DEPENDENCIES:self.assertFalse(h.registry.card(cid).metadata.collectible)
        for cid in native.EVIDENCE:self.assertNotIn(cid,h.registry.cards)
        self.assertFalse(d['new_standard_roots']);self.assertFalse(d['membership_uses_executable_coverage'])
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_complete_95_container_and_real_ordered_nine_candidate_view(self):
        h=host();d=native.load_batch();p=h.registry.pool(NATURE_PAST_POOL,h.context)
        self.assertEqual(p.members,tuple(PoolMember(cid)for cid in d['merged_member_ids']))
        self.assertEqual(p.members[:86],tuple(PoolMember(cid)for cid in d['original_member_ids']))
        values=resolve_candidates(h.registry,h.context,p.id,QUERIES[WO],current_class=CardClass.ROGUE,source_card_id=WO,exclude_source_by_rule=True)
        self.assertEqual([v.card_id for v in values],list(native.ROOTS));self.assertEqual([v.weight for v in values],[1]*9)

    def test_strict_pool_rejects_cropped_reordered_reweighted_or_borrowed_source(self):
        h=host();p=h.registry.pool(NATURE_PAST_POOL,h.context)
        class Proxy:
            def __getattr__(self,key):return getattr(h.registry,key)
            def pool(self,*args):return self.changed
        for patch in ({'members':p.members[:-1]},{'members':tuple(reversed(p.members))},
                {'members':(replace(p.members[0],weight=2),)+p.members[1:]},{'complete':False},{'version':'borrowed'},{'target_id':'other'}):
            with self.subTest(patch=tuple(patch)):
                q=Proxy();q.changed=replace(p,**patch)
                with self.assertRaises(TargetValidationError):native.register_scope(q,h.context)

    def test_late_member_failure_cannot_register_partial_source_scope(self):
        h=host();calls=[]
        class Proxy:
            def __getattr__(self,key):return getattr(h.registry,key)
            def card(self,cid):return replace(h.registry.card(cid),cost=9)if cid==native.ROOTS[-1]else h.registry.card(cid)
            def register_generation_scope(self,v):calls.append(v)
        with self.assertRaises(TargetValidationError):native.register_scope(Proxy(),h.context)
        self.assertEqual(calls,[])

    def test_all_five_weapon_spells_require_actual_equipment_without_payment(self):
        for cid in native.WEAPON_REQUIRED:
            with self.subTest(card=cid):
                g=self.game((cid,));saved=deepcopy(g.snapshot())
                with self.assertRaises(IllegalAction):self.play(g,cid)
                self.assertEqual(g.snapshot(),saved)

    def test_deadly_poison_pays_real_cost_and_permanently_modifies_only_current_weapon(self):
        g=self.game(('CS2_074',W2),weapon=W);old=self.weapon(g).id;self.play(g,'CS2_074')
        self.assertEqual((self.weapon(g).attack,self.weapon(g).durability,g.state.players[1].mana),(4,2,9))
        self.next_turn(g);self.assertEqual(self.weapon(g).attack,4)
        self.play(g,W2);self.assertNotEqual(self.weapon(g).id,old);self.assertEqual(self.weapon(g).attack,1);self.portable(g)

    def test_paralytic_poison_grants_only_attack_immunity_and_uses_plus_one(self):
        g=self.game(('BAR_321',HURT),weapon=W,enemy=(B,));self.play(g,'BAR_321')
        self.assertEqual(self.weapon(g).attack,3);self.assertIn(Keyword.IMMUNE_WHILE_ATTACKING,self.weapon(g).keywords)
        target=self.entity(g,B,2,'board').id;health=self.hero(g).health;self.attack(g,target)
        self.assertEqual(self.hero(g).health,health);self.assertEqual(g.state.entities[target].health,6)
        self.play(g,HURT);self.assertEqual(self.hero(g).health,health-9);self.portable(g)

    def test_leeching_poison_heals_real_attack_damage_and_expires_at_this_turn_end(self):
        g=self.game((HURT,'ICC_221'),weapon=W,enemy=(A,));self.play(g,HURT);self.play(g,'ICC_221')
        self.assertIn(Keyword.LIFESTEAL,self.weapon(g).keywords);self.attack(g,self.entity(g,A,2,'board').id)
        self.assertEqual(self.hero(g).health,23);self.assertEqual(g.state.players[1].mana,9)
        g.apply(EndTurn(1));self.assertNotIn(Keyword.LIFESTEAL,self.weapon(g).keywords);self.portable(g)

    def test_envenom_weapon_uses_real_poisonous_death_instead_of_extra_numeric_damage(self):
        g=self.game(('UNG_823',),weapon=W,enemy=(A,));target=self.entity(g,A,2,'board').id;self.play(g,'UNG_823')
        self.assertEqual(g.state.players[1].mana,8);self.assertIn(Keyword.POISONOUS,self.weapon(g).keywords)
        self.attack(g,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.death_history),1);self.assertEqual(self.weapon(g).attack,2);self.portable(g)

    def test_two_silverleaf_grants_draw_independently_on_both_hits_including_final_wear(self):
        g=self.game(('BAR_318','BAR_318'),weapon=W);wid=self.weapon(g).id
        self.play(g,'BAR_318');self.play(g,'BAR_318');self.attack(g)
        self.assertEqual(len([e for e in g.events if e.kind=='card_drawn'and e.source_id==wid]),2)
        self.next_turn(g);self.attack(g)
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(len([e for e in g.events if e.kind=='card_drawn'and e.source_id==wid]),4);self.portable(g)

    def test_silverleaf_last_attack_wait_keeps_reward_after_replacement_and_failed_selection(self):
        g=self.game(('BAR_318',),weapon=LAST,watch='attack');wid=self.weapon(g).id;self.play(g,'BAR_318');self.attack(g)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'replace');self.finish(g)
        self.assertEqual(self.weapon(g).card_id,W2)
        self.assertEqual(len([e for e in g.events if e.kind=='card_drawn'and e.source_id==wid]),1);self.portable(g)

    def test_razorpetal_volley_delivers_two_real_one_cost_spells_and_petals_deal_two(self):
        g=self.game(('UNG_057',));self.play(g,'UNG_057');self.assertEqual(self.ids(g),['UNG_057t1']*2)
        ids=tuple(g.state.players[1].hand);self.assertNotEqual(ids[0],ids[1]);self.play(g,'UNG_057t1',self.hero(g,2).id)
        self.assertEqual((self.hero(g,2).health,g.state.players[1].mana),(28,7));self.portable(g)

    def test_razorpetal_second_delivery_uses_existing_overflow_instead_of_silent_drop(self):
        g=self.game(('UNG_057',)+(A,)*9);self.play(g,'UNG_057')
        self.assertEqual(self.ids(g).count('UNG_057t1'),1)
        self.assertEqual(len([e for e in g.state.entities.values()if e.card_id=='UNG_057t1']),2)
        self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),1)

    def test_mimic_pod_copies_original_drawn_current_stats_and_cost_to_same_player(self):
        g=self.game((PREP,'UNG_060'),deck=(A,B));self.play(g,PREP);self.play(g,'UNG_060')
        cards=[g.state.entities[i]for i in g.state.players[1].hand];self.assertEqual([c.card_id for c in cards],[A,A])
        self.assertNotEqual(cards[0].id,cards[1].id);self.assertEqual([(c.attack,c.health,c.cost)for c in cards],[(2,11,0)]*2)
        self.assertEqual(len(g.state.draw_history),1);self.assertEqual(self.ids(g,player=2),[]);self.portable(g)

    def test_mimic_pod_empty_deck_has_fatigue_without_invented_copy_or_rng(self):
        g=self.game(('UNG_060',),deck=());rng=g.snapshot()['rng_state'];self.play(g,'UNG_060')
        self.assertEqual(self.ids(g),[]);self.assertEqual(self.hero(g).health,29);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_mimic_pod_full_hand_burns_extra_copy_and_records_one_actual_draw(self):
        g=self.game(('UNG_060',)+(B,)*9,deck=(A,));self.play(g,'UNG_060')
        self.assertEqual(self.ids(g).count(A),1);self.assertEqual(len(g.state.draw_history),1)
        self.assertEqual(len([e for e in g.state.entities.values()if e.card_id==A and e.zone==Zone.GRAVEYARD]),1)

    def test_mimic_pod_wait_restore_transform_and_failed_resume_keep_original_copy_material(self):
        g=self.game(('UNG_060',),deck=(A,B),watch='draw');self.play(g,'UNG_060')
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'transform')
        self.assertEqual(self.ids(g),[B,A]);self.portable(g)

    def test_mimic_pod_interleaved_draw_does_not_replace_the_original_operand(self):
        g=self.game(('UNG_060',),deck=(A,B),watch='draw');self.play(g,'UNG_060');self.choose(g,'interleave')
        self.assertEqual(self.ids(g),[B,A]);self.assertEqual(self.ids(g,'deck'),[A]);self.portable(g)

    def test_hallucination_uses_actual_opponent_class_excluding_own_and_neutral(self):
        g=self.game(('UNG_856',));self.play(g,'UNG_856');q=g.state.pending_choice
        self.assertEqual({o.card_id for o in q.options},set(WARS));self.assertEqual(g.state.players[1].mana,9)
        other=json.dumps(g.for_player(2).observe())
        for cid in WARS:self.assertNotIn(cid,other)
        self.portable(g);self.choose(g,q.options[0].id)
        self.assertNotIn(self.ids(g)[0],json.dumps(g.for_player(2).observe()));self.portable(g)

    def test_nitro_base_only_buffs_target_and_real_higher_card_corrupts_original_hand_entity(self):
        g=self.game(('YOP_015',),board=(A,),weapon=W);self.play(g,'YOP_015',self.entity(g,A,zone='board').id)
        self.assertEqual((self.entity(g,A,zone='board').attack,self.weapon(g).attack),(2,2))
        g=self.game(('YOP_015',HIGH),board=(A,),weapon=W);original=self.entity(g,'YOP_015').id;self.play(g,HIGH)
        self.assertEqual(g.state.entities[original].card_id,'YOP_015t');self.assertEqual(self.entity(g,'YOP_015t').id,original)
        self.play(g,'YOP_015t',self.entity(g,A,zone='board').id)
        self.assertEqual((self.entity(g,A,zone='board').attack,self.weapon(g).attack),(2,4));self.portable(g)

    def test_corrupted_nitro_still_buffs_minion_without_weapon_and_rejects_hero_target(self):
        g=self.game(('YOP_015t',),board=(A,));saved=deepcopy(g.snapshot())
        with self.assertRaises(IllegalAction):self.play(g,'YOP_015t',self.hero(g).id)
        self.assertEqual(g.snapshot(),saved);self.play(g,'YOP_015t',self.entity(g,A,zone='board').id)
        self.assertEqual(self.entity(g,A,zone='board').attack,2);self.assertIsNone(g.state.players[1].weapon_id)

    def test_corrupted_nitro_wait_retains_original_weapon_reference_without_buffing_replacement(self):
        g=self.game(('YOP_015t',),board=(A,),weapon=W,watch='buff');old=self.weapon(g).id
        self.play(g,'YOP_015t',self.entity(g,A,zone='board').id);self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        self.choose(g,'replace');self.finish(g);self.assertEqual(self.weapon(g).card_id,W2)
        self.assertEqual(self.weapon(g).attack,1);self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.portable(g)

    def test_new_draw_reward_rejects_amount_callback_and_unrecognized_aliases(self):
        self.assertEqual(DrawGroupReward('copy_self').kind,'copy_self')
        for call in (lambda:DrawGroupReward('copy_self',1),lambda:DrawGroupReward('copy_self',behavior_id=FAIL),lambda:DrawGroupReward('copy_any')):
            with self.assertRaises(ValueError):call()

    def test_actual_wo_generates_real_rogue_source_card_then_normal_paid_payload_runs(self):
        g=self.actual(seed=1);self.play(g,'CORE_EX1_169');q=g.state.pending_choice
        self.assertEqual(len(q.options),3);self.assertTrue({o.card_id for o in q.options}<=set(native.ROOTS))
        self.assertEqual([o.card_id for o in q.options],['CS2_074','BAR_321','UNG_057'])
        self.portable(g)
        # Seed-specific expected card is pinned after pure candidate sampling.
        chosen=next(o for o in q.options if o.card_id=='UNG_057');self.choose(g,chosen.id)
        self.assertNotIn('UNG_057',json.dumps(g.for_player(2).observe()));mana=g.state.players[1].mana
        self.play(g,'UNG_057');self.assertEqual(g.state.players[1].mana,mana-2)
        self.assertEqual(self.ids(g).count('UNG_057t1'),2);self.assertIsNotNone(g.state.pending_choice)
        self.finish(g);self.portable(g)

    def test_unreviewed_shaman_cannot_use_an_implemented_subset(self):
        g=self.actual(hero='HERO_02');saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.play(g,'CORE_EX1_169')
        self.assertEqual(g.snapshot(),saved)


if __name__=='__main__':unittest.main()
