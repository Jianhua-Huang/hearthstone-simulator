"""Actual linked card entries; controlled pools are separate experimental fixtures."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json,unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_linked_discovery_summons as native
from hs_sim.engine import (Attack,CardClass,DeckPolicy,DeckSpec,EndTurn,Game,MatchSetup,
    PlayerSetup,Scenario,SelectChoice,UseHeroPower)
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,CopyMinion,Damage,Destroy,Draw,
    GainArmor,InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence,TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError,SnapshotError
from hs_sim.engine.joust import Joust
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.model import (CardDefinition,CardType,ChoicePurpose,CostSpec,Keyword,
    LimitedTriggerSpec,SecretSpec,TargetSpec,Zone)
from hs_sim.engine.pools import (DiscoverFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember)
from hs_sim.engine.registry import Registry,UnsupportedDefinitionError
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.zones import CardReference,ModifyStoredCost
from hs_sim.local_pool_format import build_cn37_local_pool_format

KNIGHT,JUSTICAR,TAVISH,HANAR,MYRA,GREY,NITHOGG,MALYGOS,YSERA,ARCHIMONDE=native.ROOTS
EGG,WHELP,BOLT,MISSILES,NOVA,POLY,TOME,EXPLOSION,INTELLECT,FIREBALL,FLAMES,SHEEP,PORTAL=native.DEPENDENCIES
P='k733.'
A,B2,B3,B5,DRAGON,DEMON,DONOR,TAKA=tuple(P+x for x in('a','beast2','beast3','beast5','dragon','demon','donor'))+('DINO_430',)
S_HUNTER,S_MAGE,S_ROGUE=(P+x for x in('hunter_secret','mage_secret','rogue_secret'))
KILL,HUSH,RETURN,COPY,EARLY,DRAW,BUFF,DISCOUNT,SET_SECRET,FILL=(P+x for x in
    ('kill','hush','return','copy','early','draw','buff','discount','set_secret','fill'))
WATCH_SELECT,WATCH_RANDOM,WATCH_JOUST,WATCH_SUMMON,WATCH_GIFT,WATCH_START=(P+x for x in
    ('watch_select','watch_random','watch_joust','watch_summon','watch_gift','watch_start'))
FAIL,REENTER=P+'fail',P+'reenter'
CTX=GenerationContext(P+'complete-diagnostic-pool','experimental')


@lru_cache(None)
def full(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer',mode='small'):
    h=full(role);r=h.registry if mode=='host'else Registry(P+'diagnostic-v1')
    if mode!='host':
        heroes=tuple('HERO_'+str(i).zfill(2)for i in range(1,12))
        for cid in (*heroes,*native.EXISTING,'HERO_11bpt','GAME_005',TAKA):
            if cid in r.cards:continue
            card=h.registry.card(cid)
            bids=[getattr(card,k,None)for k in('on_play','battlecry','combo','deathrattle','on_use','on_discard','on_destroyed')]
            bids += [t.behavior_id for t in card.triggers]
            bids += [t.behavior_id for t in card.limited_triggers]
            for bid in dict.fromkeys(b for b in bids if b is not None):
                if bid not in r._behaviors:r.register_behavior(bid,h.registry.behavior(bid))
            if card.use_rule is not None and card.use_rule not in r._use_rules:
                r.register_use_rule(card.use_rule,h.registry.use_rule(card.use_rule),visibility='player')
            r.register_card(card)
            if cid in h.registry.pool_cards:r.register_pool_card(h.registry.pool_card(cid))
        native.register_past_linked_discovery_summons(r)
    plain=metadata(collectible=False,tribes=())
    r.register_behavior(P+'donor_cry',lambda c:(GainArmor(c.player_id,90),))
    r.register_behavior(P+'donor_death',lambda c:(GainArmor(c.player_id,7),))
    r.register_behavior(P+'demon_cry',lambda c:(AddToHand(c.player_id,DEMON,c.source_id),
        AddToHand(c.player_id,ARCHIMONDE,c.source_id,cost=CostSpec(set_to=0)),GainArmor(c.player_id,3)))
    rows=((A,2,2,12,plain,{}),(B2,2,3,6,metadata(tribes=('beast',)),{}),
        (B3,3,3,3,metadata(tribes=('beast',)),{}),(B5,5,4,6,metadata(tribes=('beast',)),{}),
        (DRAGON,2,1,9,metadata(tribes=('dragon',)),dict(battlecry=P+'donor_cry')),
        (DEMON,0,1,2,metadata(tribes=('demon',)),dict(battlecry=P+'demon_cry')),
        (DONOR,2,1,4,metadata(tribes=()),dict(battlecry=P+'donor_cry',deathrattle=P+'donor_death')))
    for cid,cost,atk,hp,meta,extra in rows:
        card=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=atk,health=hp,metadata=meta,**extra)
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_behavior(P+'secret_body',lambda c:());r.register_secret_condition(P+'never',lambda c:False)
    for cid,klass in((S_HUNTER,CardClass.HUNTER),(S_MAGE,CardClass.MAGE),(S_ROGUE,CardClass.ROGUE)):
        card=CardDefinition(cid,cid,CardType.SPELL,cost=1,keywords=(Keyword.SECRET,),
            secret=SecretSpec(cid,('turn_started',),P+'never',P+'secret_body'),metadata=metadata(klass,tribes=()))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    def discount(c):return(ModifyStoredCost(CardReference.capture(c.state.entities[c.target_id]),CostSpec(delta=-3),c.source_id),)
    def reenter(c):
        return(SummonFromZone(c.player_id,zone=Zone.HAND,selection='first',source_id=c.source_id,cause=SummonCause.capture(c)),)
    r.register_behavior(REENTER,reenter)
    bodies={KILL:lambda c:(Destroy(c.target_id,c.source_id),),HUSH:lambda c:(Silence(c.target_id),),
        RETURN:lambda c:(ReturnToHand(c.target_id),),COPY:lambda c:(CopyMinion(capture_board_presence(c.state,c.target_id),c.player_id,cause=SummonCause.capture(c)),),
        EARLY:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),
        BUFF:lambda c:(Buff(c.target_id,2,3,c.source_id),),DISCOUNT:discount,
        SET_SECRET:lambda c:(SetSecret(c.player_id,S_HUNTER),),
        FILL:lambda c:tuple(AddToHand(c.player_id,A,c.source_id)for _ in range(10))}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        target=TargetSpec(zones=(Zone.BOARD,Zone.HAND,Zone.DECK))if cid==DISCOUNT else TargetSpec()
        card=CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=plain,
            targeting=target if cid in(KILL,HUSH,RETURN,COPY,EARLY,BUFF,DISCOUNT)else None)
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K733 intentional rollback')))
    def relevant(c):
        e=c.event;s=c.state.entities.get(e.source_id);t=c.state.entities.get(e.target_id)
        return(e.kind=='choice_selected'and s is not None and s.card_id==MYRA or
            e.kind=='random_choice'and s is not None and s.card_id==GREY or
            e.kind=='joust_resolved'and s is not None and s.card_id==KNIGHT or
            e.kind=='minion_summoned'and e.action>0 and t is not None and t.card_id in(B2,DRAGON,WHELP)or
            e.kind=='card_added_to_hand'and s is not None and s.card_id in(MYRA,MALYGOS)or
            e.kind=='turn_started'and e.player_id==c.player_id)
    def wait(c):
        if not relevant(c):return()
        options=(ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fill','Fill actual hand before delivery',tuple(AddToHand(c.player_id,A,c.source_id)for _ in range(10))),
            ChoiceOption('fault','Fault',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))))
        bodies=[c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id in native.ROOTS+(EGG,A)]
        body=next((e for e in bodies if e.card_id in(MYRA,KNIGHT,EGG)),bodies[0]if bodies else None)
        if body is not None:
            options+=(ChoiceOption('remove','Remove original',(Destroy(body.id,c.source_id),)),
                ChoiceOption('return','Return original',(ReturnToHand(body.id),)),
                ChoiceOption('reenter','Return and summon same physical card',(ReturnToHand(body.id),InvokeBehavior(REENTER,c.source_id,c.player_id))))
        return(RequestChoice(c.player_id,options,c.source_id),)
    for cid,event in((WATCH_SELECT,'choice_selected'),(WATCH_RANDOM,'random_choice'),(WATCH_JOUST,'joust_resolved'),
            (WATCH_SUMMON,'minion_summoned'),(WATCH_GIFT,'card_added_to_hand'),(WATCH_START,'turn_started')):
        r.register_behavior(cid,wait);r.register_trigger_condition(cid,relevant)
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=40,metadata=plain,
            limited_triggers=(LimitedTriggerSpec(event,cid,cid),)))
    if mode!='host':
        members=tuple(PoolMember(cid)for cid in(DRAGON,DONOR,TAKA,S_HUNTER,S_MAGE,S_ROGUE))
        r.register_pool(PoolDefinition(native.POOL,P+'members-v1',CTX.target_id,CTX.mode,members))
    r.validate();return r,h.context if mode=='host'else CTX


class LinkedDiscoverySummonTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode)[0])
    def game(self,hand=(),*,board=(),enemy=(),deck=None,enemy_deck=None,mode='small',watch=None,hero='HERO_08',seed=733):
        self.mode=mode;r,ctx=fixture('writer',mode)
        return Game.from_scenario(Scenario((PlayerSetup(hero,hero_power_card_id=r.card(hero).initial_hero_power,hand=hand,board=board,deck=(A,)*12 if deck is None else deck,
            mana=40,max_mana=40,mana_cap=40,armor=500,weapon_card_id=watch),
            PlayerSetup('HERO_08',hero_power_card_id='HERO_08bp',board=enemy,deck=(A,)*12 if enemy_deck is None else enemy_deck,
            mana=40,max_mana=40,mana_cap=40,armor=500)),seed=seed,generation_context=ctx),r)
    def opening(self,mode='small'):
        self.mode=mode;r,ctx=fixture('writer',mode)
        policy=DeckPolicy(P+'opening-v1',ctx.target_id,ctx.mode,tuple(r.cards),max_copies=30)
        decks=tuple(DeckSpec('HERO_08',r.card('HERO_08').initial_hero_power,CardClass.MAGE,(DEMON,)*30)for _ in(1,2))
        g=Game.from_decks(MatchSetup(decks,policy,'GAME_005',seed=733,first_player=1),r)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        return g
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def faces(self,g,p=1,zone='hand'):return[g.state.entities[i].card_id for i in getattr(g.state.players[p],zone)]
    def drain(self,g):
        while g.state.pending_choice:self.choose(g,g.state.pending_choice.options[0].id)
    def pick(self,g,cid):
        q=g.state.pending_choice;name=g.registry.card(cid).name
        self.choose(g,next(o.id for o in q.options if o.label==name))
    def fault(self,g):
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
    def granted(self,g,cid=MYRA):return[a for a in self.unit(g,cid).abilities if a.deathrattle_discovered_from is not None]

    def test_complete_source_roles_all_children_original_powers_and_independent_definitions(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),48)
        self.assertEqual(sum(len(d[k])for k in('cards','dependencies','existing_dependencies','evidence_only')),59)
        self.assertEqual(len(d['original_candidate_ids']),732);self.assertEqual(len(d['existing_dependencies']),29)
        for cid in native.ROOTS+native.DEPENDENCIES:self.assertEqual(fixture()[0].card(cid),fixture('independent-reader')[0].card(cid))
        for row in d['existing_dependencies']:
            cid=row['record']['id'];self.assertEqual(cid in fixture()[0].pool_cards,row['pool_card_present'])
        self.assertEqual((fixture()[0].card(BOLT).cost,fixture()[0].card(EGG).attack),(0,0))

    def test_all_ten_current_host_real_entries_and_all_thirteen_children(self):
        for cid in native.ROOTS[:-1]+native.DEPENDENCIES:
            with self.subTest(cid=cid):
                g=self.game((cid,DRAGON),enemy=(A,),mode='host');before=g.state.players[1].mana
                target=self.unit(g,A,2).id if cid in(BOLT,FIREBALL,POLY)else None
                self.play(g,cid,target);self.drain(g)
                self.assertEqual(g.state.players[1].mana,before-g.registry.card(cid).cost)
                self.assertTrue(any(row.card_id==cid for row in g.state.play_history))
        g=self.opening('host');self.play(g,DEMON);self.play(g,ARCHIMONDE)
        self.assertTrue(any(row.card_id==ARCHIMONDE for row in g.state.play_history))

    def test_fixed_discovery_keeps_all_nine_exact_unit_members_without_ordinary_pool_registration(self):
        from hs_sim.engine.fixed_card_discovery import candidates
        r=fixture()[0];spec=DiscoverFromPool(1,native.FIXED_DISCOVERY,source_id=1,fixed_candidates=native.UPGRADED_SPELLS)
        rows=candidates(r,spec);self.assertEqual(tuple(x.card_id for x in rows),tuple(sorted(native.UPGRADED_SPELLS)))
        self.assertTrue(all(x.weight==1 for x in rows));self.assertNotIn(SHEEP,[x.card_id for x in rows])
        self.assertNotIn(native.FIXED_DISCOVERY,{p.id for p in r.pools.values()})

    def test_fixed_discovery_rejects_cropped_shape_unknown_member_and_collectible_override(self):
        from hs_sim.engine.fixed_card_discovery import candidates
        r=fixture()[0]
        for fields in(dict(pool_id=native.FIXED_DISCOVERY),dict(pool_id=native.POOL,fixed_candidates=native.UPGRADED_SPELLS),
                dict(pool_id=native.FIXED_DISCOVERY,fixed_candidates=(BOLT,BOLT)),
                dict(pool_id=native.FIXED_DISCOVERY,fixed_candidates=(BOLT,),destination='board')):
            with self.subTest(fields=fields),self.assertRaises(ValueError):DiscoverFromPool(1,source_id=1,**fields)
        for cid in(P+'unknown',S_MAGE):
            with self.subTest(cid=cid),self.assertRaises((ValueError,ResolutionError,UnsupportedDefinitionError)):
                candidates(r,DiscoverFromPool(1,native.FIXED_DISCOVERY,source_id=1,fixed_candidates=(BOLT,cid)))

    def test_Knight_natural_win_returns_original_reset_physical_card(self):
        g=self.game((KILL,BUFF),board=(KNIGHT,),deck=(B5,),enemy_deck=(B2,));old=self.unit(g,KNIGHT)
        self.play(g,BUFF,old.id);self.play(g,KILL,old.id)
        new=self.entity(g,KNIGHT);self.assertEqual(new.id,old.id);self.assertEqual((new.attack,new.max_health),(7,4));self.portable(g)

    def test_Knight_tie_loss_and_empty_deck_comparisons(self):
        for own,enemy,won in(((B2,),(B2,),False),((B2,),(B5,),False),((),(B2,),False),((B5,),(),True),((),(),False)):
            with self.subTest(own=own,enemy=enemy):
                g=self.game((KILL,),board=(KNIGHT,),deck=own,enemy_deck=enemy);eid=self.unit(g,KNIGHT).id
                self.play(g,KILL,eid);self.assertEqual(g.state.entities[eid].zone,Zone.HAND if won else Zone.GRAVEYARD)

    def test_Knight_early_win_returns_original_live_body_and_full_hand_burns(self):
        g=self.game((EARLY,),board=(KNIGHT,),deck=(B5,),enemy_deck=(B2,));eid=self.unit(g,KNIGHT).id
        self.play(g,EARLY,eid);self.assertEqual(self.entity(g,KNIGHT).id,eid)
        g=self.game((KILL,)+(A,)*9,board=(KNIGHT,),deck=(B5,),enemy_deck=(B2,));self.play(g,KILL,self.unit(g,KNIGHT).id)
        self.assertIn(KNIGHT,self.faces(g))
        g=self.game((EARLY,),board=(KNIGHT,),deck=(B5,),enemy_deck=(B2,),watch=WATCH_JOUST)
        eid=self.unit(g,KNIGHT).id;self.play(g,EARLY,eid);self.choose(g,'fill')
        self.assertNotIn(KNIGHT,self.faces(g));self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)

    def test_Knight_original_winner_wait_restore_and_reentry_does_not_return_later_residence(self):
        g=self.game((EARLY,),board=(KNIGHT,),deck=(B5,),enemy_deck=(B2,),watch=WATCH_JOUST)
        eid=self.unit(g,KNIGHT).id;self.play(g,EARLY,eid);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g);self.fault(g);self.choose(g,'reenter')
        self.assertEqual(g.state.entities[eid].zone,Zone.BOARD);self.assertNotIn(KNIGHT,self.faces(g));self.portable(g)

    def test_Justicar_upgrades_all_eleven_actual_basic_power_identities(self):
        for number,(basic,upgrade)in enumerate(native.UPGRADES.items(),1):
            with self.subTest(basic=basic):
                g=self.game((JUSTICAR,),hero='HERO_'+str(number).zfill(2));self.play(g,JUSTICAR)
                power=g.state.entities[g.state.players[1].hero_power_id];self.assertEqual(power.card_id,upgrade)
        self.portable(g)

    def test_Justicar_replacement_after_using_basic_power_refreshes_new_power_once(self):
        g=self.game((JUSTICAR,JUSTICAR));power=g.state.players[1].hero_power_id
        g.apply(UseHeroPower(1,power,g.state.players[2].hero_id));self.play(g,JUSTICAR)
        upgraded=g.state.players[1].hero_power_id;self.assertNotEqual(upgraded,power)
        g.apply(UseHeroPower(1,upgraded,g.state.players[2].hero_id));self.play(g,JUSTICAR)
        self.assertEqual(g.state.players[1].hero_power_id,upgraded);self.portable(g)

    def test_Tavish_real_Beast_attack_recruits_exact_original_one_cheaper_without_Battlecry(self):
        g=self.game((),board=(TAVISH,B3),deck=(B2,B5));eid=self.entity(g,B2,zone='deck').id
        g.apply(Attack(1,self.unit(g,B3).id,g.state.players[2].hero_id))
        self.assertEqual(self.unit(g,B2).id,eid);self.assertEqual(self.faces(g,zone='deck'),[B5]);self.portable(g)

    def test_Tavish_naturally_dead_attacker_uses_exact_frozen_cost_and_type(self):
        g=self.game((),board=(TAVISH,B3),enemy=(B5,),deck=(B2,));dead=self.unit(g,B3).id
        g.apply(Attack(1,dead,self.unit(g,B5,2).id));self.assertEqual(g.state.entities[dead].zone,Zone.GRAVEYARD)
        self.assertIn(B2,self.faces(g,zone='board'));self.portable(g)

    def test_Tavish_current_deck_discount_and_non_Beast_exclusion(self):
        g=self.game((DISCOUNT,),board=(TAVISH,B3),deck=(B5,));eid=self.entity(g,B5,zone='deck').id
        self.play(g,DISCOUNT,eid);g.apply(Attack(1,self.unit(g,B3).id,g.state.players[2].hero_id))
        self.assertIn(B5,self.faces(g,zone='board'));self.assertEqual(self.unit(g,B5).id,eid)
        g=self.game((),board=(TAVISH,A),deck=(B2,));old=g.snapshot()['rng_state']
        g.apply(Attack(1,self.unit(g,A).id,g.state.players[2].hero_id));self.assertEqual(self.faces(g,zone='deck'),[B2])
        self.assertEqual(g.snapshot()['rng_state'],old)

    def test_Tavish_recruit_wait_restore_uses_real_delivery(self):
        g=self.game((),board=(TAVISH,B3),deck=(B2,),watch=WATCH_SUMMON)
        g.apply(Attack(1,self.unit(g,B3).id,g.state.players[2].hero_id));self.portable(g);self.fault(g);self.choose(g)
        self.assertIn(B2,self.faces(g,zone='board'))

    def test_Hanar_other_class_means_played_Secret_class_rather_than_hero_class(self):
        g=self.game((S_HUNTER,),board=(HANAR,));self.play(g,S_HUNTER)
        self.assertEqual({o.label for o in g.state.pending_choice.options},{S_MAGE,S_ROGUE})
        self.portable(g);self.pick(g,S_MAGE);self.assertIn(S_MAGE,self.faces(g));self.portable(g)

    def test_Hanar_direct_Secret_install_and_silenced_provider_do_not_discover(self):
        g=self.game((SET_SECRET,HUSH,S_MAGE),board=(HANAR,));self.play(g,SET_SECRET)
        self.assertIsNone(g.state.pending_choice);self.play(g,HUSH,self.unit(g,HANAR).id);self.play(g,S_MAGE)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(g.state.card_discovery_history)

    def test_Myra_real_discovery_grants_only_printed_Deathrattle_and_gets_selected_card(self):
        g=self.game((MYRA,KILL));eid=self.play(g,MYRA);self.portable(g);self.pick(g,DONOR)
        self.assertEqual((self.unit(g,MYRA).attack,self.unit(g,MYRA).max_health),(4,2))
        self.assertIn(DONOR,self.faces(g));self.assertEqual(len(self.granted(g)),1)
        self.assertEqual(self.hero(g).armor,500);self.play(g,KILL,eid)
        self.assertEqual(self.hero(g).armor,507);self.portable(g)

    def test_Myra_real_native_memory_donor_starts_with_fresh_empty_material(self):
        g=self.game((MYRA,EARLY));self.play(g,MYRA);self.pick(g,TAKA)
        ability,=self.granted(g);self.assertEqual(ability.deathrattle_memory.discoveries,())
        self.assertEqual(ability.deathrattle_card_id,TAKA);self.play(g,EARLY,self.unit(g,MYRA).id)
        self.assertEqual(self.faces(g,zone='board'),[MYRA]);self.portable(g)

    def test_Myra_full_hand_burn_still_grants_selected_Deathrattle(self):
        g=self.game((MYRA,)+(A,)*9,watch=WATCH_SELECT);self.play(g,MYRA);self.pick(g,DONOR)
        self.assertIsNotNone(g.state.pending_choice);self.choose(g,'fill')
        self.assertEqual(len(self.granted(g)),1);self.assertNotIn(DONOR,self.faces(g));self.assertEqual(len(g.state.players[1].hand),10);self.portable(g)

    def test_Myra_departed_or_same_id_reentered_recipient_is_not_rebound(self):
        for choice in('return','reenter'):
            with self.subTest(choice=choice):
                g=self.game((MYRA,),watch=WATCH_SELECT);eid=self.play(g,MYRA);self.pick(g,DONOR)
                self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g,choice)
                self.assertIn(DONOR,self.faces(g));self.assertFalse(any(a.deathrattle_discovered_from for a in g.state.entities[eid].abilities))
                self.portable(g)

    def test_Myra_current_copy_keeps_original_selection_and_silence_removes_grant(self):
        g=self.game((MYRA,COPY,HUSH,EARLY));eid=self.play(g,MYRA);self.pick(g,DONOR);self.play(g,COPY,eid)
        bodies=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==MYRA]
        self.assertEqual(len(bodies),2);self.assertEqual([len([a for a in b.abilities if a.deathrattle_discovered_from])for b in bodies],[1,1])
        self.play(g,HUSH,eid);self.play(g,EARLY,bodies[1].id);self.assertEqual(self.hero(g).armor,507);self.portable(g)

    def test_Myra_selection_provenance_tampering_and_erasure_rejected_after_rehash(self):
        g=self.game((MYRA,));eid=self.play(g,MYRA);self.pick(g,DONOR)
        for changed in(None,dict(battlecry_id=1,discovery_id=1,card_id=TAKA)):
            data=deepcopy(g.snapshot());abilities=data['state']['entities'][str(eid)]['abilities']
            row=next(a for a in abilities if a['deathrattle_discovered_from']is not None)
            row['deathrattle_discovered_from']=changed
            data['state_hash']=canonical_hash({k:v for k,v in data.items()if k not in('schema_version','events','events_hash','state_hash')})
            with self.subTest(changed=changed),self.assertRaises(SnapshotError):Game.from_snapshot(data,fixture('independent-reader')[0])

    def test_Myra_delivery_wait_restores_granted_payload_and_failed_choice_is_atomic(self):
        g=self.game((MYRA,),watch=WATCH_GIFT);self.play(g,MYRA);self.pick(g,DONOR)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(self.granted(g)),1)
        self.portable(g);self.fault(g);self.choose(g);self.portable(g)

    def test_Greybough_real_death_grants_random_ally_and_its_death_summons_fresh_Greybough(self):
        g=self.game((KILL,KILL),board=(GREY,A));source=self.unit(g,GREY).id
        self.play(g,KILL,source);ally=self.unit(g,A);self.assertTrue(any(a.behavior_id==native.PREFIX+'grey_child'for a in ally.abilities))
        self.play(g,KILL,ally.id);fresh=self.unit(g,GREY);self.assertNotEqual(fresh.id,source)
        self.assertEqual((fresh.attack,fresh.max_health),(4,6));self.assertIn(Keyword.TAUNT,fresh.keywords);self.portable(g)

    def test_Greybough_empty_natural_pool_consumes_no_rng_and_early_live_can_choose_self(self):
        g=self.game((KILL,),board=(GREY,));rng=g.snapshot()['rng_state'];self.play(g,KILL,self.unit(g,GREY).id)
        self.assertEqual(g.snapshot()['rng_state'],rng)
        g=self.game((EARLY,),board=(GREY,));eid=self.unit(g,GREY).id;self.play(g,EARLY,eid)
        self.assertTrue(any(a.behavior_id==native.PREFIX+'grey_child'for a in self.unit(g,GREY).abilities));self.portable(g)

    def test_Greybough_selected_original_ally_leaving_during_random_wait_gets_no_grant(self):
        g=self.game((KILL,),board=(GREY,A),watch=WATCH_RANDOM);self.play(g,KILL,self.unit(g,GREY).id)
        self.portable(g);self.fault(g);self.choose(g,'return');self.assertFalse(any(a.behavior_id==native.PREFIX+'grey_child'for a in self.entity(g,A).abilities));self.portable(g)

    def test_Nithogg_two_exact_Eggs_hatch_only_at_controllers_next_start(self):
        g=self.game((NITHOGG,));self.play(g,NITHOGG);eggs=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==EGG]
        self.assertEqual(len(eggs),2);ids=[e.id for e in eggs];self.assertTrue(all((e.attack,e.max_health)==(0,3)for e in eggs))
        g.apply(EndTurn(1));self.assertTrue(all(g.state.entities[i].card_id==EGG for i in ids))
        g.apply(EndTurn(2));self.assertTrue(all(g.state.entities[i].card_id==WHELP for i in ids))
        self.assertTrue(all((g.state.entities[i].attack,g.state.entities[i].max_health)==(4,4)and Keyword.RUSH in g.state.entities[i].keywords for i in ids));self.portable(g)

    def test_Egg_silence_removes_hatch_and_start_wait_does_not_transform_reentered_original(self):
        g=self.game((HUSH,),board=(EGG,));eid=self.unit(g,EGG).id;self.play(g,HUSH,eid)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(g.state.entities[eid].card_id,EGG)
        g=self.game((),board=(EGG,),watch=WATCH_START);eid=self.unit(g,EGG).id
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.portable(g);self.fault(g);self.choose(g,'reenter')
        self.assertEqual(g.state.entities[eid].card_id,EGG);self.assertEqual(g.state.entities[eid].zone,Zone.BOARD);self.portable(g)

    def test_Malygos_requires_other_current_hand_Dragon_and_no_condition_no_rng(self):
        g=self.game((MALYGOS,));rng=g.snapshot()['rng_state'];self.play(g,MALYGOS)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],rng)
        g=self.game((MALYGOS,DRAGON));self.play(g,MALYGOS);self.assertEqual(len(g.state.pending_choice.options),3);self.portable(g)

    def test_Malygos_all_nine_actually_discovered_spells_execute_their_complete_effects(self):
        from random import Random
        from hs_sim.engine.pools import sample_candidates
        members=tuple(PoolMember(cid)for cid in sorted(native.UPGRADED_SPELLS))
        seeds={cid:next(seed for seed in range(200)if cid in sample_candidates(Random(seed),members,3,replacement=False))for cid in native.UPGRADED_SPELLS}
        for cid in native.UPGRADED_SPELLS:
            with self.subTest(cid=cid):
                g=self.game((MALYGOS,DRAGON),enemy=(A,A),seed=seeds[cid]);self.play(g,MALYGOS);self.pick(g,cid)
                targets=list(g.state.players[2].board);before=self.hero(g).armor;olddeck=len(g.state.players[1].deck)
                target=targets[0]if cid in(BOLT,FIREBALL,POLY)else None;self.play(g,cid,target)
                self.assertEqual(self.hero(g).armor,before)
                if cid==BOLT:self.assertEqual(g.state.entities[target].health,9);self.assertTrue(g.state.entities[target].frozen)
                if cid==FIREBALL:self.assertEqual(g.state.entities[target].health,4)
                if cid==POLY:self.assertEqual(g.state.entities[target].card_id,SHEEP);self.assertEqual(g.state.entities[target].health,1)
                if cid==NOVA:self.assertTrue(all(g.state.entities[i].frozen for i in targets))
                if cid in(EXPLOSION,FLAMES):self.assertEqual([g.state.entities[i].health for i in targets],[10,10]if cid==EXPLOSION else[4,4])
                if cid==INTELLECT:self.assertEqual(len(g.state.players[1].deck),olddeck-4)
                if cid==TOME:self.assertEqual(sum(x==S_MAGE for x in self.faces(g)),3)
                if cid==MISSILES:self.assertEqual(sum(e.amount for e in g.events if e.kind=='damage_dealt'and e.source_id==self.entity_or_play_source(g,cid)),6)

    def entity_or_play_source(self,g,cid):return next(p.source_id for p in reversed(g.state.play_history)if p.card_id==cid)

    def test_Malygos_actual_discovery_delivery_wait_restores_fixed_original_offer(self):
        g=self.game((MALYGOS,DRAGON),watch=WATCH_GIFT);self.play(g,MALYGOS);self.portable(g)
        self.choose(g,g.state.pending_choice.options[0].id);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g);self.fault(g);self.choose(g);self.portable(g)

    def test_Ysera_shuffles_exactly_seven_actual_Portals_as_one_semantic_shuffle(self):
        g=self.game((YSERA,));self.play(g,YSERA)
        self.assertEqual(self.faces(g,zone='deck').count(PORTAL),7);self.assertEqual(len(g.state.deck_shuffle_history),1)
        self.assertEqual(g.state.deck_shuffle_history[0].declared_count,7);self.portable(g)

    def test_Portal_real_draw_cast_summons_complete_Dragon_candidate_without_Battlecry_then_draws(self):
        g=self.game((DRAW,),deck=(PORTAL,A));self.play(g,DRAW)
        self.assertEqual(self.faces(g),[A]);self.assertEqual(self.faces(g,zone='board'),[DRAGON])
        self.assertEqual(self.hero(g).armor,500);self.assertEqual(len(g.state.cast_history),2);self.portable(g)

    def test_Portal_full_board_still_consumes_draw_cast_and_actual_replacement_fatigue(self):
        g=self.game((DRAW,),board=(A,)*7,deck=(PORTAL,));self.play(g,DRAW)
        self.assertEqual(len(g.state.players[1].board),7);self.assertFalse(self.faces(g));self.assertEqual(self.hero(g).armor,499)
        self.assertEqual(len(g.state.cast_history),2);self.portable(g)

    def test_Portal_actual_summon_wait_restores_original_automatic_CAST_and_replacement_draw(self):
        g=self.game((DRAW,),deck=(PORTAL,A),watch=WATCH_SUMMON);self.play(g,DRAW)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.fault(g);self.choose(g)
        self.assertEqual(self.faces(g),[A]);self.portable(g)

    def test_Archimonde_real_opening_distinguishes_same_name_generated_original_and_current_self(self):
        g=self.opening();original=self.entity(g,DEMON).id;self.play(g,DEMON)
        generated=next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==DEMON and i!=original and i not in g.state.opening.original_entities[0])
        from hs_sim.engine import PlayCard
        g.apply(PlayCard(1,generated.id));self.play(g,ARCHIMONDE)
        self.assertEqual(self.faces(g,zone='board').count(DEMON),3);self.assertEqual(self.faces(g,zone='board').count(ARCHIMONDE),2)
        self.assertEqual(self.hero(g).armor,6);self.portable(g)

    def test_Archimonde_unknown_original_deck_fails_transactionally_instead_of_guessing(self):
        g=self.game((ARCHIMONDE,));saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Starting-deck physical identity is unknown')as failure:self.play(g,ARCHIMONDE)
        self.assertIsInstance(failure.exception.__cause__,UnsupportedDefinitionError)
        self.assertEqual(g.snapshot(),saved)

    def test_private_discovered_payload_and_original_receipts_never_enter_either_player_view(self):
        g=self.game((MYRA,));self.play(g,MYRA);self.pick(g,DONOR)
        for player in(1,2):
            text=json.dumps(g.for_player(player).observe())
            for field in('deathrattle_discovered_from','card_discovery_history','resolution_frame','rng_state','deathrattle_memory'):
                self.assertNotIn('"'+field+'"',text)
        self.portable(g)

