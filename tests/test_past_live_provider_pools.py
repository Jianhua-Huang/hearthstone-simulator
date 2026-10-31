"""Real paid entries, physical Tracking, hidden Secrets and original stat gains."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
from random import Random
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_live_provider_pools as native
from hs_sim.engine import Attack,EndTurn,Game,PlayerSetup,Ruleset,Scenario,UseHeroPower
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,CopyMinion,Damage,DamageBatch,Destroy,
    GainArmor,GrantKeyword,Heal,InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence,TriggerDeathrattles)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import (CardClass,CardDefinition,CardType,CostSpec,Keyword,LimitedTriggerSpec,
    Rarity,SecretSpec,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.native_stat_gains import EVENT,LABEL,NativeStatGainProfile
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.zones import CardReference,ModifyStoredCost
from hs_sim.local_pool_format import build_cn37_local_pool_format

SAIDAN,LUMIA,NAIELLE,NEPTULON,COLLECTOR,QUEEN,PUTRICIDE,ROTFACE,HADRONOX,HELBRIM=native.ROOTS
TRACKING=native.TRACKING
P='k732.'
A,TAUNT,M1,M2,D1,D2,L1,L2=(P+x for x in('a','taunt','m1','m2','d1','d2','l1','l2'))
S1,S2,S3,SMAGE=(P+x for x in('s1','s2','alias','mage_secret'))
(NOOP,HIGH,BUFF,ATK,HP,MIXED,DEBUFF,HIT,LETHAL,KILL,HUSH,BOUNCE,TAUNT_GRANT,COPY,STORED_HAND,STORED_DECK,
PAIR_HERO,HEAL,SET_S1,SUMMON_NEPT,EARLY,FILL)=(P+x for x in('noop','high','buff','atk','hp','mixed','debuff','hit','lethal',
    'kill','hush','bounce','taunt_grant','copy','stored_hand','stored_deck','pair_hero','heal','set_s1','summon_nept','early','fill'))
WAIT_STATS,WAIT_HEALTH,WAIT_GIFT,WAIT_SUMMON,FAIL,WEAPON=(P+x for x in('wait_stats','wait_health','wait_gift','wait_summon','fail','weapon'))
CTX=GenerationContext(P+'fixture','experimental')
UNKNOWN=P+'unknown_secret'


@lru_cache(None)
def full(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer',mode='small'):
    h=full(role);r=h.registry if mode=='host'else defaults()
    if mode!='host':
        for cid in native.EXISTING:
            card=h.registry.card(cid)
            if cid not in r.cards:
                for bid in(card.on_play,card.battlecry,card.deathrattle):
                    if bid is not None:r.register_behavior(bid,h.registry.behavior(bid))
                r.register_card(card)
            if cid not in r.pool_cards:r.register_pool_card(h.registry.pool_card(cid))
        native.register_past_live_provider_pools(r)
    plain=metadata(collectible=False,tribes=())
    r.register_behavior(P+'cry',lambda c:(GainArmor(c.player_id,90),))
    for cid,meta,extra in((A,plain,{}),(TAUNT,plain,dict(keywords=(Keyword.TAUNT,))),
            (M1,metadata(CardClass.PALADIN,tribes=('murloc',)),{}),(M2,metadata(CardClass.WARRIOR,tribes=('murloc',)),{}),
            (D1,metadata(tribes=('dragon',)),{}),(D2,metadata(CardClass.PRIEST,tribes=('dragon',)),{}),
            (L1,metadata(rarity=Rarity.LEGENDARY,tribes=()),dict(battlecry=P+'cry')),
            (L2,metadata(CardClass.WARRIOR,rarity=Rarity.LEGENDARY,tribes=()),{})):
        card=CardDefinition(cid,cid,CardType.MINION,cost=2,attack=3,health=8,metadata=meta,**extra)
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_behavior(P+'never_body',lambda c:());r.register_secret_condition(P+'never',lambda c:False)
    for cid,klass,key in((S1,CardClass.HUNTER,S1),(S2,CardClass.HUNTER,S2),(S3,CardClass.HUNTER,S1),(SMAGE,CardClass.MAGE,SMAGE)):
        card=CardDefinition(cid,cid,CardType.SPELL,cost=1,keywords=(Keyword.SECRET,),
            secret=SecretSpec(key,('turn_started',),P+'never',P+'never_body'),metadata=metadata(klass,tribes=()))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    def stored(c,zone):
        e=next(c.state.entities[i]for i in getattr(c.state.players[c.player_id],zone.value)if c.state.entities[i].card_id==SAIDAN)
        return(BuffStoredCard(CardReference.capture(e),2,3,c.source_id),)
    bodies={NOOP:lambda c:(),HIGH:lambda c:(),BUFF:lambda c:(Buff(c.target_id,2,3,c.source_id),),
        ATK:lambda c:(Buff(c.target_id,3,0,c.source_id),),HP:lambda c:(Buff(c.target_id,0,4,c.source_id),),
        MIXED:lambda c:(Buff(c.target_id,2,-1,c.source_id),),DEBUFF:lambda c:(Buff(c.target_id,-1,0,c.source_id),),
        HIT:lambda c:(Damage(c.target_id,2,c.source_id),),LETHAL:lambda c:(Damage(c.target_id,100,c.source_id),),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),HUSH:lambda c:(Silence(c.target_id),),
        BOUNCE:lambda c:(ReturnToHand(c.target_id),),TAUNT_GRANT:lambda c:(GrantKeyword(c.target_id,Keyword.TAUNT,c.source_id),),
        COPY:lambda c:(CopyMinion(capture_board_presence(c.state,c.target_id),c.player_id,cause=SummonCause.capture(c)),),
        STORED_HAND:lambda c:stored(c,Zone.HAND),STORED_DECK:lambda c:stored(c,Zone.DECK),
        PAIR_HERO:lambda c:tuple(Damage(c.state.players[p].hero_id,2,c.source_id)for p in(1,2)),
        HEAL:lambda c:(Heal(c.target_id,2,c.source_id),),SET_S1:lambda c:(SetSecret(c.player_id,S1),),
        SUMMON_NEPT:lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(NEPTULON),),SummonCause.capture(c)),),
        EARLY:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        FILL:lambda c:(AddToHand(c.player_id,NOOP,c.source_id),AddToHand(c.player_id,NOOP,c.source_id))}
    targets=(BUFF,ATK,HP,MIXED,DEBUFF,HIT,LETHAL,KILL,HUSH,BOUNCE,TAUNT_GRANT,COPY,HEAL,EARLY)
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        card=CardDefinition(cid,cid,CardType.SPELL,cost=8 if cid==HIGH else 0,on_play=cid,
            targeting=TargetSpec()if cid in targets else None,metadata=plain)
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    def relevant(c):
        return(c.event.kind=='stats_changed'and c.event.target_id is not None and
            c.state.entities[c.event.target_id].card_id==SAIDAN or
            c.event.kind=='health_resolved'and c.health_result.damage_dealt>0 or
            c.event.kind=='card_added_to_hand'and c.event.source_id is not None and
            c.state.entities[c.event.source_id].card_id in(NEPTULON,COLLECTOR,HELBRIM)or
            c.event.kind=='minion_summoned'and c.event.action>0 and c.event.target_id is not None and
            c.state.entities[c.event.target_id].card_id in(TAUNT,L1,L2,QUEEN))
    def wait(c):
        if not relevant(c):return()
        options=(ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fault','Fault',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))))
        original=next((c.state.entities[i]for i in c.state.players[1].board if c.state.entities[i].card_id in native.ROOTS),None)
        if original is not None:options+=(ChoiceOption('remove','Remove original source',(Destroy(original.id,c.source_id),)),)
        if original is not None:options+=(ChoiceOption('return','Return original source',(ReturnToHand(original.id),)),)
        return(RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K732 deliberate rollback')))
    for cid,event in((WAIT_STATS,'stats_changed'),(WAIT_HEALTH,'health_resolved'),(WAIT_GIFT,'card_added_to_hand'),(WAIT_SUMMON,'minion_summoned')):
        r.register_behavior(cid,wait);r.register_trigger_condition(cid,relevant)
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=40,metadata=plain,
            limited_triggers=(LimitedTriggerSpec(event,cid,cid),)))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,attack=2,durability=5,metadata=plain))
    if mode!='host':
        members=tuple(PoolMember(i,3 if i in(M2,S2)else 1)for i in(M1,M2,D1,D2,L1,L2,QUEEN,S1,S2,S3,SMAGE))
        if mode=='unknown':
            r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,1,metadata(CardClass.HUNTER,tribes=()),keywords=(Keyword.SECRET,)))
            members+= (PoolMember(UNKNOWN),)
        if mode=='empty':members=()
        r.register_pool(PoolDefinition(native.POOL,P+'pool',CTX.target_id,CTX.mode,members))
    r.validate();return r,h.context if mode=='host'else CTX


class LiveProviderPoolTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode)[0])
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=None,enemy_deck=None,mode='small',watch=None,seed=732,armor=500,rules=None):
        self.mode=mode;r,ctx=fixture('writer',mode)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(A,)*10 if deck is None else deck,
            mana=40,max_mana=40,mana_cap=40,armor=armor,weapon_card_id=watch),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(A,)*10 if enemy_deck is None else enemy_deck,
            mana=40,max_mana=40,mana_cap=40,armor=armor)),seed=seed,generation_context=ctx),r,ruleset=rules)
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def faces(self,g,p=1,zone='hand'):return[g.state.entities[i].card_id for i in getattr(g.state.players[p],zone)]
    def stats(self,g,eid):e=g.state.entities[eid];return(e.attack,e.max_health)
    def drain(self,g):
        while g.state.pending_choice:self.choose(g)
    def fault(self,g):
        snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),snap)

    def test_complete_twenty_rows_thirty_six_primary_faces_and_eleven_original_definitions(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),36);self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(sum(len(d[k])for k in('cards','dependencies','existing_dependencies','evidence_only')),20)
        for cid in native.ROOTS+native.DEPENDENCIES:self.assertEqual(fixture()[0].card(cid),fixture('independent-reader')[0].card(cid))
        self.assertNotIn(Keyword.TAUNT,fixture()[0].card(HADRONOX).keywords)
        self.assertEqual((fixture()[0].card(TRACKING).kind,fixture()[0].card(TRACKING).cost),(CardType.HERO_POWER,1))
        self.assertEqual(d['fixed_poison_weights'],[1]*5);self.assertFalse(d['official_poison_pool_verified'])

    def test_exact_Neptulon_separator_pin_rejects_changed_complete_source_and_primary(self):
        from tools import card_batch as cb
        d=native.load_batch();raw=next(x['record']for x in d['cards']if x['record']['id']==NEPTULON)
        for o in d['official_observations']:
            if o['card_id']!=NEPTULON:continue
            cb.check_face(raw,o['face'],o['locale'],d['display_normalizations'][NEPTULON])
            changed=deepcopy(raw);changed['text'if o['locale']=='zh_CN'else'text_en']+='new rule'
            with self.assertRaises(ValueError):cb.check_face(changed,o['face'],o['locale'],d['display_normalizations'][NEPTULON])
            changed=deepcopy(o['face']);changed['text']+=' new rule'
            with self.assertRaises(ValueError):cb.check_face(raw,changed,o['locale'],d['display_normalizations'][NEPTULON])

    def test_all_ten_roots_use_current_host_real_paid_hand_entries(self):
        for cid in native.ROOTS:
            g=self.game((cid,),mode='host');sid=self.play(g,cid);self.drain(g)
            self.assertTrue(g.state.play_history[0].completed);self.assertEqual(g.state.play_history[0].source_id,sid)

    def test_Saidan_combined_gain_doubles_each_positive_amount_once(self):
        g=self.game((BUFF,),board=(SAIDAN,));eid=self.unit(g,SAIDAN).id;self.play(g,BUFF,eid)
        self.assertEqual(self.stats(g,eid),(6,8));self.assertEqual(len([e for e in g.events if e.kind==EVENT]),1)
        self.assertEqual(sum(e.label==LABEL for e in g.state.entities[eid].enchantments),1);self.portable(g)

    def test_Saidan_attack_only_health_only_signed_and_nonpositive_operations(self):
        for spell,expected in((ATK,(8,2)),(HP,(2,10)),(MIXED,(6,1)),(DEBUFF,(1,2))):
            g=self.game((spell,),board=(SAIDAN,));eid=self.unit(g,SAIDAN).id;self.play(g,spell,eid)
            self.assertEqual(self.stats(g,eid),expected)
            self.assertEqual(len([e for e in g.events if e.kind==EVENT]),0 if spell==DEBUFF else 1)

    def test_Saidan_actual_hand_and_deck_attachments_preserve_original_physical_card(self):
        for zone,spell in(('hand',STORED_HAND),('deck',STORED_DECK)):
            g=self.game((spell,SAIDAN)if zone=='hand'else(spell,),deck=(SAIDAN,A)if zone=='deck'else None)
            eid=self.entity(g,SAIDAN,zone=zone).id;self.play(g,spell)
            self.assertEqual(self.stats(g,eid),(6,8));self.assertEqual(g.state.entities[eid].zone,Zone(zone));self.portable(g)

    def test_Saidan_silence_removes_reward_and_current_copy_does_not_replay_inherited_gains(self):
        g=self.game((BUFF,COPY,HUSH,BUFF),board=(SAIDAN,));eid=self.unit(g,SAIDAN).id
        self.play(g,BUFF,eid);self.play(g,COPY,eid)
        copies=[i for i in g.state.players[1].board if g.state.entities[i].card_id==SAIDAN]
        self.assertEqual([self.stats(g,i)for i in copies],[(6,8),(6,8)])
        self.assertEqual(len([e for e in g.events if e.kind==EVENT]),1)
        self.play(g,HUSH,eid);self.play(g,BUFF,eid);self.assertEqual(self.stats(g,eid),(4,5));self.portable(g)

    def test_Saidan_original_reward_wait_restore_replay_and_failed_choice_atomicity(self):
        g=self.game((BUFF,),board=(SAIDAN,),watch=WAIT_STATS);eid=self.unit(g,SAIDAN).id;self.play(g,BUFF,eid)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.fault(g);self.drain(g)
        self.assertEqual(self.stats(g,eid),(6,8));self.portable(g)

    def test_Saidan_profile_default_and_strict_mode_remain_explicit(self):
        self.assertEqual(NativeStatGainProfile('JAIL_330').mode,'one_one')
        self.assertEqual(fixture()[0].native_stat_gain_profiles[SAIDAN].mode,'double_positive')
        with self.assertRaises(ValueError):NativeStatGainProfile(SAIDAN,'multiply_everything')

    def test_Lumia_both_original_heroes_gain_turn_immunity_after_positive_damage(self):
        g=self.game((PAIR_HERO,HIT,HUSH),board=(LUMIA,));self.play(g,PAIR_HERO)
        self.assertTrue(all(Keyword.IMMUNE in self.hero(g,p).keywords for p in(1,2)))
        self.assertEqual((self.hero(g).armor,self.hero(g,2).armor),(498,498))
        self.play(g,HIT,self.hero(g).id);self.assertEqual(self.hero(g).armor,498)
        self.play(g,HUSH,self.unit(g,LUMIA).id);self.assertIn(Keyword.IMMUNE,self.hero(g).keywords)
        g.apply(EndTurn(1));self.assertTrue(all(Keyword.IMMUNE not in self.hero(g,p).keywords for p in(1,2)));self.portable(g)

    def test_Lumia_healing_zero_damage_and_minion_damage_do_not_grant_hero_immunity(self):
        g=self.game((HEAL,HIT),board=(LUMIA,A));self.play(g,HEAL,self.hero(g).id);self.play(g,HIT,self.unit(g,A).id)
        self.assertNotIn(Keyword.IMMUNE,self.hero(g).keywords);self.assertNotIn(Keyword.IMMUNE,self.hero(g,2).keywords)

    def test_Lumia_actual_Lifesteal_attack_heals_and_damage_still_uses_original_health_pipeline(self):
        g=self.game((HIT,),board=(LUMIA,),armor=0);self.play(g,HIT,self.hero(g).id)
        self.assertEqual(self.hero(g).health,28);g.apply(EndTurn(1));g.apply(EndTurn(2))
        g.apply(Attack(1,self.unit(g,LUMIA).id,self.hero(g,2).id));self.assertEqual(self.hero(g).health,30)
        self.assertEqual(self.hero(g,2).health,21);self.assertIn(Keyword.IMMUNE,self.hero(g,2).keywords);self.portable(g)

    def test_Lumia_waiting_real_health_result_restores_without_leaking_private_material(self):
        g=self.game((HIT,),board=(LUMIA,),watch=WAIT_HEALTH);self.play(g,HIT,self.hero(g,2).id)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.fault(g);self.drain(g)
        self.assertIn(Keyword.IMMUNE,self.hero(g,2).keywords);self.portable(g)

    def test_Naielle_installs_real_one_cost_Tracking_and_takes_original_deck_card(self):
        g=self.game((NAIELLE,STORED_DECK),deck=(SAIDAN,D1,D2),mode='host');self.play(g,STORED_DECK)
        originals=set(g.state.players[1].deck);sid=self.entity(g,SAIDAN,zone='deck').id;self.play(g,NAIELLE)
        power=g.state.entities[g.state.players[1].hero_power_id];self.assertEqual(power.card_id,TRACKING)
        before=len(g.state.draw_history);mana=g.state.players[1].mana;g.apply(UseHeroPower(1,power.id))
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.players[1].mana,mana-1);self.portable(g)
        q=g.state.pending_choice;chosen=next(o.id for o in q.options if o.label==fixture('writer','host')[0].card(SAIDAN).name)
        self.choose(g,chosen);self.assertIn(sid,g.state.players[1].hand);self.assertEqual(self.stats(g,sid),(6,8))
        self.assertEqual(set(g.state.players[1].deck),originals-{sid});self.assertEqual(len(g.state.draw_history),before)
        self.portable(g)

    def test_Tracking_empty_deck_spends_one_mana_once_without_draw_or_fatigue(self):
        g=self.game((NAIELLE,),deck=());self.play(g,NAIELLE);power=g.state.players[1].hero_power_id;g.apply(UseHeroPower(1,power))
        self.assertEqual(g.state.players[1].mana,36);self.assertFalse(g.state.pending_choice);self.assertFalse(g.state.draw_history)
        with self.assertRaises(IllegalAction):g.apply(UseHeroPower(1,power))
        self.portable(g)

    def test_Neptulon_four_complete_cross_class_weighted_Murlocs_and_single_Overload(self):
        g=self.game((NEPTULON,));r,ctx=fixture();rng=Random();rng.setstate(g._rng.getstate())
        candidates=resolve_candidates(r,ctx,native.POOL,native.MURLOCS,source_card_id=NEPTULON,player_id=1,exclude_source_by_rule=True)
        self.assertEqual({m.card_id for m in candidates},{M1,M2});expected=sample_candidates(rng,candidates,4,replacement=True)
        self.play(g,NEPTULON);self.assertEqual(tuple(self.faces(g)),expected);self.assertEqual(g._rng.getstate(),rng.getstate())
        self.assertEqual(g.state.players[1].overload_owed,3);g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(g.state.players[1].overload_locked,3);self.portable(g)

    def test_Neptulon_ordinary_summon_has_no_Battlecry_or_Overload(self):
        g=self.game((SUMMON_NEPT,));rng=g._rng.getstate();self.play(g,SUMMON_NEPT)
        self.assertEqual(self.faces(g,zone='board'),[NEPTULON]);self.assertFalse(self.faces(g));self.assertEqual(g.state.players[1].overload_owed,0)
        self.assertEqual(g._rng.getstate(),rng)

    def test_Neptulon_complete_random_batch_survives_first_gift_choice_and_original_source_death(self):
        g=self.game((NEPTULON,),watch=WAIT_GIFT);self.play(g,NEPTULON);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g);self.fault(g);self.choose(g,'remove');self.drain(g)
        self.assertEqual(len(self.faces(g)),4);self.assertEqual(g.state.players[1].overload_owed,3);self.portable(g)

    def test_Face_Collector_real_Echo_copy_and_each_paid_Battlecry_generates_Legendary(self):
        g=self.game((COLLECTOR,));self.play(g,COLLECTOR);first=self.entity(g,COLLECTOR)
        self.assertIsNotNone(first.hand_lifetime);self.assertEqual(first.hand_lifetime.minimum_cost,1)
        self.play(g,COLLECTOR);self.assertEqual(self.faces(g,zone='board').count(COLLECTOR),2)
        gifts=[i for i in g.state.players[1].hand if g.state.entities[i].card_id!=COLLECTOR]
        self.assertEqual(len(gifts),2);self.assertTrue(all(g.state.entities[i].card_id in(L1,L2,QUEEN)for i in gifts))
        g.apply(EndTurn(1));self.assertNotIn(COLLECTOR,self.faces(g));self.portable(g)

    def test_Dragonqueen_duplicate_deck_does_nothing_and_unique_deck_gives_two_other_zero_cost_Dragons(self):
        g=self.game((QUEEN,),deck=(A,A));rng=g._rng.getstate();self.play(g,QUEEN)
        self.assertFalse(self.faces(g));self.assertEqual(g._rng.getstate(),rng)
        g=self.game((QUEEN,),deck=(A,));self.play(g,QUEEN);self.assertEqual(len(self.faces(g)),2)
        self.assertTrue(set(self.faces(g))<={D1,D2});self.assertNotIn(QUEEN,self.faces(g))
        self.assertTrue(all(g.state.entities[i].cost==0 for i in g.state.players[1].hand));self.portable(g)

    def test_Putricide_only_real_own_Secret_play_installs_one_additional_hidden_Hunter_Secret(self):
        g=self.game((S1,),board=(PUTRICIDE,));self.play(g,S1)
        self.assertEqual(self.faces(g,zone='secrets'),[S1,S2]);self.assertEqual(len(g.state.play_history),1)
        self.assertEqual(len(g.state.cast_history),1);self.assertEqual(g.state.players[1].mana,39)
        self.assertFalse([e for e in g.events if e.kind=='random_choice'])
        view=json.dumps(g.for_player(2).observe());self.assertNotIn(S2,view);self.assertNotIn(S1,view);self.portable(g)

    def test_Putricide_ordinary_SetSecret_and_opponent_play_do_not_trigger(self):
        g=self.game((SET_S1,),board=(PUTRICIDE,),enemy_hand=(S2,));self.play(g,SET_S1)
        self.assertEqual(self.faces(g,zone='secrets'),[S1]);g.apply(EndTurn(1));self.play(g,S2,player=2)
        self.assertEqual(self.faces(g,zone='secrets'),[S1]);self.assertEqual(self.faces(g,2,'secrets'),[S2]);self.portable(g)

    def test_Putricide_duplicate_key_alias_and_empty_remaining_inventory_consume_no_randomness(self):
        g=self.game((SET_S1,S2),board=(PUTRICIDE,));self.play(g,SET_S1);rng=g._rng.getstate();self.play(g,S2)
        self.assertEqual(set(self.faces(g,zone='secrets')),{S1,S2});self.assertEqual(g._rng.getstate(),rng)

    def test_Putricide_full_shared_area_does_not_draw_allocate_or_create_an_extra_CAST(self):
        g=self.game((S1,),board=(PUTRICIDE,),rules=Ruleset(max_secret_zone=1))
        rng=g._rng.getstate();next_id=g.state.next_entity_id;self.play(g,S1)
        self.assertEqual(self.faces(g,zone='secrets'),[S1]);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(g.state.next_entity_id,next_id);self.assertEqual(len(g.state.cast_history),1);self.portable(g)

    def test_Putricide_unknown_eligible_Secret_is_not_silently_removed_and_entire_play_rolls_back(self):
        g=self.game((S1,),board=(PUTRICIDE,),mode='unknown');snap=g.snapshot()
        with self.assertRaises((ValueError,ResolutionError)):self.play(g,S1)
        self.assertEqual(g.snapshot(),snap)

    def test_Rotface_only_original_positive_nonlethal_self_damage_summons_without_Battlecry(self):
        g=self.game((HIT,),board=(ROTFACE,));armor=self.hero(g).armor;self.play(g,HIT,self.unit(g,ROTFACE).id)
        bodies=[cid for cid in self.faces(g,zone='board')if cid!=ROTFACE]
        self.assertEqual(len(bodies),1);self.assertIn(bodies[0],(L1,L2,QUEEN));self.assertEqual(self.hero(g).armor,armor)
        self.portable(g)

    def test_Rotface_lethal_damage_other_minion_damage_and_full_board(self):
        for hand,board,target,expected in(((LETHAL,),(ROTFACE,),ROTFACE,0),((HIT,),(ROTFACE,A),A,2),
                ((HIT,),(ROTFACE,A,A,A,A,A,A),ROTFACE,7)):
            g=self.game(hand,board=board);self.play(g,hand[0],self.unit(g,target).id)
            self.assertEqual(len(self.faces(g,zone='board')),expected)

    def test_Rotface_original_summon_wait_restores_and_rolls_back_failed_choice(self):
        g=self.game((HIT,),board=(ROTFACE,),watch=WAIT_SUMMON);self.play(g,HIT,self.unit(g,ROTFACE).id)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.fault(g);self.drain(g);self.portable(g)

    def test_Hadronox_all_duplicate_friendly_actual_Taunt_deaths_but_no_enemy_deaths(self):
        g=self.game((KILL,KILL,KILL,KILL),board=(TAUNT,TAUNT,HADRONOX),enemy=(TAUNT,))
        for _ in range(2):self.play(g,KILL,self.unit(g,TAUNT).id)
        self.play(g,KILL,self.unit(g,TAUNT,2).id);self.play(g,KILL,self.unit(g,HADRONOX).id)
        self.assertEqual(self.faces(g,zone='board'),[TAUNT,TAUNT]);self.assertEqual(len(g.state.resurrection_history),2);self.portable(g)

    def test_Hadronox_granted_Taunt_qualifies_but_resurrected_body_is_fresh_printed_without_grant(self):
        g=self.game((TAUNT_GRANT,KILL,KILL),board=(A,HADRONOX));eid=self.unit(g,A).id
        self.play(g,TAUNT_GRANT,eid);self.play(g,KILL,eid);self.play(g,KILL,self.unit(g,HADRONOX).id)
        new=self.unit(g,A);self.assertNotEqual(new.id,eid);self.assertNotIn(Keyword.TAUNT,new.keywords);self.portable(g)

    def test_Hadronox_lost_Taunt_at_death_is_excluded_and_empty_inventory_uses_no_RNG(self):
        g=self.game((HUSH,KILL,KILL),board=(TAUNT,HADRONOX));eid=self.unit(g,TAUNT).id
        self.play(g,HUSH,eid);self.play(g,KILL,eid);rng=g._rng.getstate();self.play(g,KILL,self.unit(g,HADRONOX).id)
        self.assertFalse(self.faces(g,zone='board'));self.assertEqual(g._rng.getstate(),rng)

    def test_Hadronox_early_Deathrattle_can_reuse_original_history_and_shared_capacity(self):
        g=self.game((KILL,EARLY,EARLY),board=(TAUNT,HADRONOX));self.play(g,KILL,self.unit(g,TAUNT).id)
        for _ in range(2):self.play(g,EARLY,self.unit(g,HADRONOX).id)
        self.assertEqual(self.faces(g,zone='board').count(TAUNT),2);self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_Hadronox_resurrection_first_delivery_wait_restores_and_does_not_consume_deaths(self):
        g=self.game((KILL,KILL),board=(TAUNT,HADRONOX),watch=WAIT_SUMMON)
        self.play(g,KILL,self.unit(g,TAUNT).id);self.play(g,KILL,self.unit(g,HADRONOX).id)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.fault(g);self.drain(g);self.portable(g)

    def test_Helbrim_Battlecry_and_Deathrattle_draw_from_full_fixed_five_independently(self):
        g=self.game((HELBRIM,KILL));self.play(g,HELBRIM);first=[i for i in g.state.players[1].hand if g.state.entities[i].card_id in native.POISONS]
        self.play(g,KILL,self.unit(g,HELBRIM).id);gifts=[i for i in g.state.players[1].hand if g.state.entities[i].card_id in native.POISONS]
        self.assertEqual(len(first),1);self.assertEqual(len(gifts),2);self.assertEqual(len(set(gifts)),2);self.portable(g)

    def test_Helbrim_five_actual_generated_Poisons_and_corrupted_dependency_execute_in_current_host(self):
        from hs_sim.engine.pools import GenerateFromCandidates
        seeds={}
        for seed in range(100):
            cid=sample_candidates(Random(seed),tuple(PoolMember(i)for i in sorted(native.POISONS)),1,replacement=True)[0]
            seeds.setdefault(cid,seed)
        self.assertEqual(set(seeds),set(native.POISONS))
        for cid,seed in seeds.items():
            g=self.game((HELBRIM,HIGH),board=(A,),enemy=(A,),mode='host',watch=WEAPON,seed=seed)
            self.play(g,HELBRIM);self.assertIn(cid,self.faces(g));weapon=g.state.entities[g.state.players[1].weapon_id]
            before=weapon.attack;target=self.unit(g,A).id
            if cid=='YOP_015':
                self.play(g,HIGH);self.assertIn('YOP_015t',self.faces(g));self.play(g,'YOP_015t',target)
                self.assertEqual(g.state.entities[target].attack,5);self.assertEqual(g.state.entities[weapon.id].attack,before+2)
            else:
                self.play(g,cid)
                if cid=='CS2_074':self.assertEqual(g.state.entities[weapon.id].attack,before+2)
                if cid=='ICC_221':self.assertIn(Keyword.LIFESTEAL,g.state.entities[weapon.id].keywords)
                if cid=='BAR_321':
                    self.assertEqual(g.state.entities[weapon.id].attack,before+1)
                    armor=self.hero(g).armor;g.apply(Attack(1,self.hero(g).id,self.unit(g,A,2).id));self.assertEqual(self.hero(g).armor,armor)
                if cid=='BAR_318':
                    draws=len(g.state.draw_history);g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id))
                    self.assertEqual(len(g.state.draw_history),draws+1)
            self.portable(g)

    def test_Helbrim_first_gift_wait_survives_original_source_removal_and_recovers(self):
        g=self.game((HELBRIM,),watch=WAIT_GIFT);self.play(g,HELBRIM);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g);self.fault(g);self.choose(g,'remove');self.drain(g)
        self.assertEqual(sum(cid in native.POISONS for cid in self.faces(g)),2);self.portable(g)


if __name__=='__main__':unittest.main()
