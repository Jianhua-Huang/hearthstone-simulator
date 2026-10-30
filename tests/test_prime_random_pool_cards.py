"""Two exact Prime chains, complete host domains and ordinary attributed execution."""
from dataclasses import asdict, replace
from functools import lru_cache
import json, unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import prime_random_pool_cards as native
from hs_sim.engine import DeckPolicy, DeckSpec, Game, MatchSetup, PlayerSetup, ResolutionError, Scenario, SelectChoice
from hs_sim.engine.automatic_targets import AutomaticTargetPreference
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Damage, Destroy, Draw, GainArmor,
    InvokeBehavior, RandomDamage, RequestChoice, Silence, Summon, TriggerDeathrattles)
from hs_sim.engine.model import (BattlecryRepeatSpec, CardClass, CardDefinition, CardType, DamageKind,
    DeathrattleRepeatSpec, Keyword, OpeningHook, SummonQuantitySpec, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.pools import (GenerationContext, PoolCard, PoolDefinition, PoolMember, SummonFromPool,
    resolve_candidates, validate_pool_entry_keywords)
from hs_sim.engine.registry import Registry
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_history import CastFromPool, ContinuePoolCasts
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.local_pool_format import build_cn37_local_pool_format

MURGUR,SOLARIAN=native.ROOTS
MP,SP=native.DEPENDENCIES
P='k714.'
M,A,BOTH_REPEAT,DR_REPEAT,QUANTITY=(P+x for x in ('murloc','plain','bc_repeat','dr_repeat','quantity'))
HIT,FRIEND,SELF_KILL,NO_TARGET,OTHER=(P+x for x in ('hit','friend','self_kill','no_target','other'))
KILL,DRAW,HUSH,CONTROL,EARLY=(P+x for x in ('kill','draw','hush','control','early'))
WAIT_SUMMON,WAIT_CAST,FAIL=(P+x for x in ('wait_summon','wait_cast','fail'))
MISSING=P+'unknown'
BOOT=P+'starting_inventory'
SECRET='CORE_EX1_287'
HELPERS=(M,A,BOTH_REPEAT,DR_REPEAT,QUANTITY,HIT,FRIEND,SELF_KILL,NO_TARGET,OTHER,KILL,DRAW,HUSH,CONTROL,EARLY,WAIT_SUMMON,WAIT_CAST)
CONTEXT=GenerationContext(P+'complete-fixture','experimental')


@lru_cache(None)
def host(role='writer'):
    h=build_cn37_local_pool_format();r=h.registry;meta=metadata(collectible=False)
    r.register_behavior(P+'marker',lambda c:(GainArmor(c.player_id,100),))
    for cid,extra in ((M,dict(battlecry=P+'marker',metadata=metadata(tribes=('murloc',)))),
            (A,{}),(BOTH_REPEAT,dict(battlecry_repeats=(BattlecryRepeatSpec(2),))),
            (DR_REPEAT,dict(deathrattle_repeats=(DeathrattleRepeatSpec(2),))),
            (QUANTITY,dict(summon_quantities=(SummonQuantitySpec(),)))):
        fields=dict(metadata=meta);fields.update(extra)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=1,health=3 if cid==M else 30,**fields))
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ResolutionError('K714 deliberate accepted continuation failure')))
    def wait(c):
        target=c.state.entities.get(c.event.target_id)
        if c.source.card_id==WAIT_SUMMON:
            if target is None or target.card_id!=M:return ()
            if Keyword.DIVINE_SHIELD not in target.keywords:raise ResolutionError('K714 Shield must exist before entry notification')
        else:
            caster=c.state.entities.get(c.event.source_id)
            if caster is None or caster.card_id not in (HIT,FRIEND):return ()
        options=(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail after RNG',(
            RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))))
        parent=next((i for i in c.state.players[1].board if c.state.entities[i].card_id in (MP,SP)),None)
        if parent is not None:options+=(ChoiceOption('control','Transfer original Prime',(ChangeControl(parent,2),)),)
        return (RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(P+'wait',wait)
    for cid,event in ((WAIT_SUMMON,'minion_summoned'),(WAIT_CAST,'spell_cast_finished')):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=30,metadata=meta,triggers=(TriggerSpec(event,P+'wait'),)))
    def self_kill(c):
        source=c.cast.caster_id
        return (Destroy(source,c.source_id),Damage(c.state.players[2].hero_id,1,c.source_id,DamageKind.SPELL))
    bodies={HIT:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),FRIEND:lambda c:(GainArmor(c.player_id,1),),
        SELF_KILL:self_kill,NO_TARGET:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        OTHER:lambda c:(GainArmor(c.player_id,900),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        DRAW:lambda c:(Draw(c.player_id,source_id=c.source_id),),HUSH:lambda c:(Silence(c.target_id),),
        CONTROL:lambda c:(ChangeControl(c.target_id,2),),EARLY:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        targeting=(TargetSpec() if cid in (HIT,KILL,HUSH,CONTROL,EARLY) else
            TargetSpec(zones=(Zone.HERO,),kinds=(CardType.HERO,),relation='friendly') if cid==FRIEND else
            TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy') if cid==NO_TARGET else None)
        card_meta=metadata(CardClass.MAGE) if cid in (HIT,FRIEND,SELF_KILL,NO_TARGET) else metadata(CardClass.WARRIOR) if cid==OTHER else meta
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=card_meta,targeting=targeting))
    for label,domain in native.load_batch()['complete_host_domains'].items():
        for row in domain['members']:
            cid=row['card_id'];driver=P+'probe.'+cid
            if label=='Mage_spells':
                def body(c,cid=cid):
                    caster=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==SP)
                    return (CastSpell(c.player_id,cid,caster,target_preference=AutomaticTargetPreference.ENEMY_IF_AVAILABLE),)
            else:
                def body(c,cid=cid):
                    return (SummonFromPool(c.player_id,native.MINIONS_POOL,replace(native.MURLOCS,card_ids=(cid,)),
                        c.source_id,cause=SummonCause.capture(c),entry_keywords=(Keyword.DIVINE_SHIELD,)),)
            r.register_behavior(driver,body);r.register_card(CardDefinition(driver,driver,CardType.SPELL,on_play=driver,metadata=meta))
    driver=P+'probe.TLC_364'
    r.register_behavior(BOOT,lambda c:(AddToHand(c.player_id,driver,c.source_id),Summon(c.player_id,SP)))
    r.register_card(CardDefinition(BOOT,BOOT,CardType.MINION,health=1,metadata=metadata(),
        opening_hooks=(OpeningHook('after_mulligan',BOOT),)))
    r.validate();return h


@lru_cache(None)
def fixture(mode='damage',role='writer'):
    full=host(role).registry;r=Registry('k714-two-real-prime-pools-'+mode+'-v1')
    for bid,body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX):r.register_behavior(bid,body)
    for key,condition in full._secret_conditions.items():r.register_secret_condition(key,condition)
    for cid in ('HERO_08','HERO_08bp','HERO_01','HERO_01bp',SECRET,*HELPERS):
        r.register_card(full.card(cid));r.register_pool_card(PoolCard.from_definition(full.card(cid)))
    native.register_prime_random_pool_cards(r)
    spells={'friendly':FRIEND,'self_kill':SELF_KILL,'no_target':NO_TARGET,'secret':SECRET}.get(mode,HIT)
    minions=[PoolMember(M),PoolMember(A)];cards=[PoolMember(spells),PoolMember(OTHER)]
    if mode=='empty':minions=[PoolMember(A)];cards=[PoolMember(OTHER)]
    if mode.startswith('unknown'):
        kind=CardType.MINION if mode=='unknown_murloc' else CardType.SPELL
        meta=metadata(tribes=('murloc',)) if kind==CardType.MINION else metadata(CardClass.MAGE)
        missing=CardDefinition(MISSING,MISSING,kind,cost=1,attack=1 if kind==CardType.MINION else 0,
            health=2 if kind==CardType.MINION else 0,metadata=meta)
        r.register_pool_card(PoolCard.from_definition(missing))
        (minions if kind==CardType.MINION else cards).append(PoolMember(MISSING))
    for pool_id,members in ((native.MINIONS_POOL,minions),(native.SPELLS_POOL,cards)):
        r.register_pool(PoolDefinition(id=pool_id,version='k714-test-only-complete',target_id=CONTEXT.target_id,
            mode=CONTEXT.mode,members=tuple(members),complete=True))
    r.validate();return r


class PrimeRandomPoolTests(CardBatchTestMixin,unittest.TestCase):
    mode='damage'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host' else fixture(mode,role))
    def game(self,hand=(),*,board=(),enemy=(),mode='damage',watch=None,real_host=False,hero='HERO_08',deck=None):
        self.mode='host' if real_host else mode
        own_deck=deck if deck is not None else (A,)*12 if real_host else ()
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=own_deck,mana=40,
            max_mana=40,mana_cap=40,armor=500 if real_host else 0,hero_power_card_id='HERO_08bp',weapon_card_id=watch),
            PlayerSetup('HERO_08',board=enemy,deck=(A,)*12,mana=40,max_mana=40,mana_cap=40,
                armor=500 if real_host else 0,hero_power_card_id='HERO_08bp')),seed=714,
            generation_context=host().context if real_host else CONTEXT),self.registry_factory(self.mode,'writer'))
    def units(self,g,cid,player=1):return [g.state.entities[i] for i in g.state.players[player].board if g.state.entities[i].card_id==cid]
    def opened_host(self):
        self.mode='host';h=host();cards=(BOOT,)+('CORE_CS2_182',)*11
        policy=DeckPolicy(P+'starting-inventory',h.target_id,h.context.mode,(BOOT,'CORE_CS2_182'),deck_size=12,max_copies=12)
        g=Game.from_decks(MatchSetup(tuple(DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,cards)for _ in (1,2)),
            policy,'GAME_005',seed=714,first_player=1),h.registry)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        return g
    def casts(self,g,source):return [r for r in g.state.cast_history if r.caster_id==source]
    def finish(self,g):
        n=0
        while g.state.pending_choice is not None:
            n+=1;self.assertLess(n,60);self.choose(g)
    def finish_any(self,g):
        n=0
        while g.state.pending_choice is not None:
            n+=1;self.assertLess(n,100)
            choices=[a for a in g.legal_actions() if isinstance(a,SelectChoice)]
            self.assertTrue(choices);g.apply(choices[0])
    def fault(self,g):
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)

    def test_full_four_source_faces_named_links_and_complete_23_51_domains(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),10);self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual([d['complete_host_domains'][key]['member_count'] for key in ('Murlocs','Mage_spells')],[23,51])
        self.assertTrue({'murloc','mech'}<=set(fixture().card(MP).metadata.tribes))
        self.assertTrue(all(not fixture().pool_card(cid).metadata.collectible for cid in native.DEPENDENCIES))

    def test_both_paid_original_roots_shuffle_exact_Prime_then_real_draw_and_entry(self):
        for parent,child in zip(native.ROOTS,native.DEPENDENCIES):
            g=self.game((parent,KILL,DRAW));eid=self.play(g,parent);self.play(g,KILL,eid)
            inserted=self.entity(g,child,zone='deck').id;self.play(g,DRAW);self.assertEqual(self.entity(g,child).id,inserted)
            self.play(g,child);self.assertEqual(g.state.players[1].mana,40-g.registry.card(parent).cost-g.registry.card(child).cost)

    def test_both_Murgur_faces_have_real_printed_Divine_Shield(self):
        for cid in (MURGUR,MP):
            g=self.game((cid,));eid=self.play(g,cid);self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords)

    def test_both_Solarian_faces_have_actual_Spell_Damage(self):
        for cid in (SOLARIAN,SP):
            g=self.game((HIT,),board=(cid,));target=g.state.players[2].hero_id;self.play(g,HIT,target)
            self.assertEqual(g.state.entities[target].health,28)

    def test_Murgur_four_actual_pool_entries_already_have_Shield_without_battlecries(self):
        g=self.game((MP,),watch=WAIT_SUMMON);self.play(g,MP);self.assertIsNotNone(g.state.pending_choice)
        self.finish(g);self.assertEqual(len(self.units(g,M)),4)
        self.assertTrue(all(Keyword.DIVINE_SHIELD in e.keywords for e in self.units(g,M)))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.assertEqual(len(g.state.battlecry_history),1);self.assertEqual(len(g.state.card_summon_history),4)

    def test_Murgur_capacity_and_quantity_use_original_shared_entry_rules(self):
        g=self.game((MP,),board=(A,)*4);self.play(g,MP);self.assertEqual(len(self.units(g,M)),2)
        self.assertEqual(len(g.state.players[1].board),7)
        g=self.game((MP,),board=(QUANTITY,));self.play(g,MP);self.assertEqual(len(self.units(g,M)),5)
        self.assertTrue(all(Keyword.DIVINE_SHIELD in e.keywords for e in self.units(g,M)))

    def test_Murgur_empty_declared_pool_skips_without_RNG(self):
        g=self.game((MP,),mode='empty');rng=g.snapshot()['rng_state'];self.play(g,MP)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(self.units(g,M),[])

    def test_unknown_eligible_Murloc_rejects_whole_paid_action_without_cropping(self):
        g=self.game((MP,),mode='unknown_murloc');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'unsupported card definition: k714.unknown'):self.play(g,MP)
        self.assertEqual(g.snapshot(),before)

    def test_Murgur_entry_wait_restores_remaining_four_requests_and_failed_choice(self):
        g=self.game((MP,),watch=WAIT_SUMMON);self.play(g,MP);g=self.portable(g);self.fault(g);self.finish(g)
        self.assertEqual(len(self.units(g,M)),4);self.portable(g)

    def test_Murgur_accepted_remaining_entries_keep_original_recipient_after_control_change(self):
        g=self.game((MP,),watch=WAIT_SUMMON);eid=self.play(g,MP);self.choose(g,'control');self.finish(g)
        self.assertEqual(g.state.entities[eid].controller,2);self.assertEqual(len(self.units(g,M)),4);self.assertEqual(self.units(g,M,2),[])
        self.portable(g)

    def test_real_early_and_repeat_deathrattles_each_shuffle_exact_child(self):
        g=self.game((SOLARIAN,EARLY,KILL),board=(DR_REPEAT,));eid=self.play(g,SOLARIAN)
        self.play(g,EARLY,eid);self.play(g,KILL,eid)
        self.assertEqual(len(g.state.players[1].deck),4);self.assertTrue(all(g.state.entities[i].card_id==SP for i in g.state.players[1].deck))

    def test_source_silence_and_control_preserve_original_shuffle_lifecycle(self):
        g=self.game((MURGUR,HUSH,KILL));eid=self.play(g,MURGUR);self.play(g,HUSH,eid);self.play(g,KILL,eid)
        self.assertEqual(g.state.players[1].deck,[])
        g=self.game((SOLARIAN,CONTROL,KILL));eid=self.play(g,SOLARIAN);self.play(g,CONTROL,eid);self.play(g,KILL,eid)
        self.assertEqual(sum(g.state.entities[i].card_id==SP for i in g.state.players[2].deck),1)

    def test_Solarian_five_free_actual_casts_use_existing_enemy_preference_receipts(self):
        g=self.game((SP,));eid=self.play(g,SP);rows=self.casts(g,eid)
        self.assertEqual(len(rows),5);self.assertTrue(all(r.card_id==HIT and r.target_id==g.state.players[2].hero_id for r in rows))
        self.assertTrue(all(r.target_selection.partition.preference is AutomaticTargetPreference.ENEMY_IF_AVAILABLE for r in rows))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,20);self.assertEqual(g.state.players[1].mana,33)
        self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_Solarian_selects_Mage_spells_even_for_Warrior_hero(self):
        g=self.game((SP,),hero='HERO_01');eid=self.play(g,SP)
        self.assertEqual({r.card_id for r in self.casts(g,eid)},{HIT});self.assertEqual(g.state.players[1].hero_class,CardClass.WARRIOR)

    def test_enemy_preference_falls_back_to_legal_friendly_targets_and_counts_fizzles(self):
        g=self.game((SP,),mode='friendly');eid=self.play(g,SP)
        self.assertEqual({r.target_id for r in self.casts(g,eid)},{g.state.players[1].hero_id})
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,5)
        g=self.game((SP,),mode='no_target');eid=self.play(g,SP)
        self.assertEqual(len(self.casts(g,eid)),5);self.assertTrue(all(r.failure=='no_target' for r in self.casts(g,eid)))

    def test_accepted_five_casts_continue_after_original_Prime_dies(self):
        g=self.game((SP,),mode='self_kill');eid=self.play(g,SP)
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertEqual(len(self.casts(g,eid)),5)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,25);self.portable(g)

    def test_Solarian_spell_wait_restores_remaining_preference_and_failure_RNG(self):
        g=self.game((SP,),watch=WAIT_CAST);eid=self.play(g,SP);self.assertIsNotNone(g.state.pending_choice)
        g=self.portable(g);self.fault(g);self.finish(g);self.assertEqual(len(self.casts(g,eid)),5);self.portable(g)

    def test_unknown_eligible_Mage_spell_rejects_before_random_choice_or_payment(self):
        g=self.game((SP,),mode='unknown_spell');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'unsupported card definition: k714.unknown'):self.play(g,SP)
        self.assertEqual(g.snapshot(),before)

    def test_empty_Mage_pool_skips_without_RNG_and_Battlecry_repeat_pays_once(self):
        g=self.game((SP,),mode='empty');rng=g.snapshot()['rng_state'];eid=self.play(g,SP)
        self.assertEqual(self.casts(g,eid),[]);self.assertEqual(g.snapshot()['rng_state'],rng)
        g=self.game((SP,),board=(BOTH_REPEAT,));eid=self.play(g,SP)
        self.assertEqual(len(self.casts(g,eid)),10);self.assertEqual(g.state.players[1].mana,33)

    def test_secret_candidates_remain_real_cast_attempts_with_duplicate_failures(self):
        g=self.game((SP,),mode='secret');eid=self.play(g,SP)
        self.assertEqual(len(self.casts(g,eid)),5);self.assertEqual(len(g.state.players[1].secrets),1);self.portable(g)

    def test_public_extensions_allow_only_typed_single_Shield_and_source_enemy_policy(self):
        validate_pool_entry_keywords((Keyword.DIVINE_SHIELD,))
        for value in (('divine_shield',),(Keyword.DIVINE_SHIELD,Keyword.TAUNT),(Keyword.DIVINE_SHIELD,Keyword.DIVINE_SHIELD)):
            with self.subTest(value=value),self.assertRaises(ValueError):validate_pool_entry_keywords(value)
        base=CastFromPool(1,native.SPELLS_POOL,native.MAGE_SPELLS,5,1)
        self.assertIsNone(base.target_preference)
        self.assertIs(replace(base,target_preference=AutomaticTargetPreference.ENEMY_IF_AVAILABLE).target_preference,AutomaticTargetPreference.ENEMY_IF_AVAILABLE)
        for preference in ('enemy_if_available',True,AutomaticTargetPreference.ANY):
            with self.subTest(preference=preference),self.assertRaises(ValueError):replace(base,target_preference=preference)
        with self.assertRaises(ValueError):replace(base,source_id=None,target_preference=AutomaticTargetPreference.ENEMY_IF_AVAILABLE)

    def test_existing_fixed_Secret_producer_rejects_new_preference_on_actual_waiting_batch(self):
        import test_disco_past_secrets as previous
        from hs_sim.engine.secret_expirations import validate_batch
        case=previous.DiscoPastSecretsTests();g=case.game(mode='set_wait',watch=True);case.cast(g)
        queued=next(w for w in (*g._frame.prefix,*g._frame.continuation) if isinstance(w,ContinuePoolCasts))
        validate_batch(g.state,g.registry,queued.spec,allow_closed=True)
        with self.assertRaisesRegex(ValueError,'original full five-cast'):
            validate_batch(g.state,g.registry,replace(queued.spec,target_preference=AutomaticTargetPreference.ENEMY_IF_AVAILABLE),allow_closed=True)

    def test_actual_host_keeps_complete_23_51_ordered_queries(self):
        h=host();d=native.load_batch()
        for key,pool_id,query in (('Murlocs',native.MINIONS_POOL,native.MURLOCS),('Mage_spells',native.SPELLS_POOL,native.MAGE_SPELLS)):
            rows=resolve_candidates(h.registry,h.context,pool_id,query)
            self.assertEqual([asdict(x) for x in rows],d['complete_host_domains'][key]['complete_ordered_members'])

    def test_every_actual_host_Murloc_has_executable_Shield_pool_entry(self):
        for row in native.load_batch()['complete_host_domains']['Murlocs']['members']:
            with self.subTest(card=row['card_id']):
                driver=P+'probe.'+row['card_id'];g=self.game((driver,),board=(MP,),real_host=True)
                self.play(g,driver);self.finish_any(g)
                delivered=[g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id==row['card_id']]
                self.assertTrue(delivered);self.assertTrue(all(Keyword.DIVINE_SHIELD in e.keywords for e in delivered))

    def test_every_actual_host_Mage_spell_has_executable_automatic_entry(self):
        for row in native.load_batch()['complete_host_domains']['Mage_spells']['members']:
            with self.subTest(card=row['card_id']):
                driver=P+'probe.'+row['card_id']
                g=self.opened_host() if row['card_id']=='TLC_364' else self.game((driver,),board=(SP,A),enemy=(A,A),real_host=True)
                source=self.units(g,SP)[0].id;self.play(g,driver);self.finish_any(g)
                self.assertTrue(any(r.card_id==row['card_id'] for r in self.casts(g,source)))
                if row['card_id']=='TLC_364':self.portable(g)

    def test_actual_host_both_original_root_Prime_chains(self):
        for parent,child in zip(native.ROOTS,native.DEPENDENCIES):
            with self.subTest(parent=parent):
                g=self.game((parent,KILL,DRAW),real_host=True,deck=())
                source=self.play(g,parent);self.play(g,KILL,source)
                generated=self.entity(g,child,zone='deck').id
                self.play(g,DRAW);self.assertEqual(self.entity(g,child).id,generated)
                self.assertEqual(self.play(g,child),generated);self.finish_any(g)
                self.assertEqual(len(g.state.deck_shuffle_history),1)
                if child==MP:
                    self.assertEqual(len(g.state.card_summon_history),4)
                else:self.assertEqual(len(self.casts(g,generated)),5)
                self.portable(g)


if __name__=='__main__':unittest.main()
