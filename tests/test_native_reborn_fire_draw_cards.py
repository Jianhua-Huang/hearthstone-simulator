"""Native retained Reborn and bonuses on the original physical drawn spell."""
from dataclasses import asdict,replace
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import reviewed_definition_digest
from hs_sim.cards.native_reborn_fire_draw_cards import load_batch
from hs_sim.engine import (AbilityInstance,CardClass,CardDefinition,CardMetadata,CardType,
    CastWhenDrawnSpec,DamageKind,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,
    SpellSchool,TriggerSpec,Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,CopyMinion,
    Damage,DamageBatch,Destroy,Draw,GainArmor,InvokeBehavior,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.errors import ResolutionError,SnapshotError
from hs_sim.engine.health_rules import spell_bonus
from hs_sim.engine.random_split_damage import RandomSplitDamage,SplitDamageScope
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.stored_spell_damage import (DrawMatchingSpellDamage,GrantStoredSpellDamage,validate_local_ability)
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard
from hs_sim.targets import canonical_digest

STEED='CAP_800';THRASH='TLC_223';PLAIN='CORE_CS2_182';FIRE='CORE_CS2_029';POLICY='full_health_enchantments'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=(),factions=(),subtypes=())


def first_spell(c):
    return next(c.state.entities[i]for i in c.state.players[c.player_id].hand
        if c.state.entities[i].card_id in(FIRE,'k54.fire','k54.waves','k54.split','k54.auto','k54.armor'))


def registry(mode=None):
    r=build_registry()
    scripts=dict(buff=lambda c:(Buff(c.target_id,3,4,c.source_id),),
        hit=lambda c:(Damage(c.target_id,2,c.source_id),),
        kill=lambda c:(Destroy(c.target_id,c.source_id),),
        silence=lambda c:(Silence(c.target_id),),bounce=lambda c:(ReturnToHand(c.target_id),),
        copy_minion=lambda c:(CopyMinion(c.target_id,c.player_id,cause=SummonCause.capture(c)),),
        copy_current=lambda c:(CopyCard(CardReference.capture(first_spell(c)),c.player_id,mode='current'),),
        copy_base=lambda c:(CopyCard(CardReference.capture(first_spell(c)),c.player_id,mode='base'),),
        grant=lambda c:(GrantStoredSpellDamage(CardReference.capture(first_spell(c)),2,c.source_id),),
        draw=lambda c:(Draw(c.player_id,source_id=c.source_id),),
        fire=lambda c:(Damage(c.target_id,3,c.source_id,kind=DamageKind.SPELL),),
        waves=lambda c:(Damage(c.target_id,1,c.source_id,kind=DamageKind.SPELL),Damage(c.target_id,1,c.source_id,kind=DamageKind.SPELL)),
        split=lambda c:(RandomSplitDamage(c.player_id,c.cast.id,c.source_id,3,SplitDamageScope(kinds=(CardType.HERO,))),),
        auto=lambda c:(DamageBatch(tuple(Damage(i,1,c.source_id,kind=DamageKind.SPELL)for i in
            (c.state.players[3-c.player_id].hero_id,*c.state.players[3-c.player_id].board))),),
        armor=lambda c:(GainArmor(c.player_id,5),),
        fail=lambda c:(AddToHand(c.player_id,'missing.k54',c.source_id),))
    def stale(c):
        ref=CardReference.capture(first_spell(c))
        return(MoveCard(ref,c.player_id,Zone.DECK,source_id=c.source_id),GrantStoredSpellDamage(ref,2,c.source_id))
    scripts['stale']=stale
    for key,body in scripts.items():
        r.register_behavior('k54.'+key,body)
        if key=='fail':continue
        extra=dict(spell_school=SpellSchool.FIRE)if key in('fire','waves','split','auto','armor')else{}
        if key=='auto':extra.update(keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())
        r.register_card(CardDefinition('k54.'+key,key,CardType.SPELL,cost=1,on_play='k54.'+key,metadata=META,
            requires_target=key in('buff','hit','kill','silence','bounce','copy_minion','fire','waves'),**extra))
    r.register_card(CardDefinition('k54.beast','Prior Beast',CardType.MINION,attack=1,health=2,
        metadata=replace(META,tribes=('beast',))))
    r.register_card(CardDefinition('k54.power','Ordinary board provider',CardType.MINION,health=3,spell_damage=1,metadata=META))
    if mode:
        def watch(c):
            event=c.event
            if mode=='fill_hand':
                return tuple(AddToHand(c.player_id,PLAIN,c.source_id)for _ in range(3-len(c.state.players[c.player_id].hand)))if c.state.entities[event.source_id].card_id==THRASH else()
            if event.kind=='minion_died':
                if c.state.entities[event.source_id].card_id!=STEED:return ()
            else:
                target=event.source_id if event.kind=='spell_cast_accepted'else event.target_id
                if target is None or c.state.entities[target].card_id not in('k54.auto','k54.fire','k54.waves',FIRE):return ()
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.player_id,0),)),
                ChoiceOption('bad','Rollback',(InvokeBehavior('k54.fail',c.source_id,c.player_id),))),c.source_id),)
        event='minion_summoned'if mode=='fill_hand'else('minion_died'if mode=='reborn_wait'else('card_drawn'if mode=='draw_wait'else'spell_cast_accepted'))
        r.register_behavior('k54.watch',watch)
        r.register_card(CardDefinition('k54.watch','Original window observer',CardType.MINION,health=8,
            triggers=(TriggerSpec(event,'k54.watch'),),metadata=META))
    return r


class NativeRebornFireDrawTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,deck=None,board=(),enemy=(),other=(),mode=None,hand_cap=None):
        return Game.from_scenario(Scenario((PlayerSetup('test.hero',hand=hand,board=board,
            deck=(PLAIN,)*8 if deck is None else deck,mana=60,max_mana=60,mana_cap=60,hand_cap=hand_cap),
            PlayerSetup('test.hero',hand=other,board=enemy,deck=(PLAIN,)*8,mana=60,max_mana=60,mana_cap=60)),seed=1054),registry(mode)if mode else self.r)
    def entity(self,g,cid,p=1,zone='board'):
        s=g.state;return next(s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid)
    def play(self,g,cid,target=None,p=1):
        source=self.entity(g,cid,p,'hand').id;result=g.apply(PlayCard(p,source,target));return source,result
    def hero(self,g,p=1):return g.state.players[p].hero_id
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def kindred(self,g):self.play(g,'k54.beast');self.cycle(g)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,mode=None):
        saved=g.snapshot();other=Game.from_snapshot(saved,registry(mode));self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved);return other
    def local(self,entity):return tuple(a for a in entity.abilities if a.kind=='spell_damage')
    def test_complete_faces_native_policy_and_both_thrasher_tribes(self):
        for row in load_batch()['cards']:
            raw=row['record'];card=self.r.card(raw['id']);self.assertEqual(canonical_digest(raw),row['record_sha256'])
            self.assertEqual((card.cost,card.attack,card.health),(raw['cost'],raw['attack'],raw['health']))
        self.assertEqual(self.r.card(STEED).reborn_policy,POLICY);self.assertEqual(self.r.card(THRASH).metadata.tribes,('elemental','beast'))
    def test_native_policy_is_printed_without_an_on_play_grant(self):
        g=self.game(board=(STEED,));e=self.entity(g,STEED);row=next(a for a in e.abilities if a.keyword==Keyword.REBORN)
        self.assertEqual((row.origin,row.source_id,row.reborn_policy),('printed',e.id,POLICY));self.assertIsNone(self.r.card(STEED).on_play)
    def test_both_cards_pay_three_mana(self):
        for cid in(STEED,THRASH):
            g=self.game((cid,));self.play(g,cid);self.assertEqual(g.state.players[1].mana,57)
    def test_native_reborn_returns_full_enchanted_health_and_consumes_reborn(self):
        g=self.game(('k54.buff','k54.hit','k54.kill'),board=(STEED,));original=self.entity(g,STEED).id
        self.play(g,'k54.buff',original);self.play(g,'k54.hit',original);self.play(g,'k54.kill',original);e=self.entity(g,STEED)
        self.assertNotEqual(e.id,original);self.assertEqual((e.attack,e.health,e.damage),(5,7,0));self.assertNotIn(Keyword.REBORN,e.keywords);self.portable(g)
    def test_second_death_does_not_reborn_again(self):
        g=self.game(('k54.kill','k54.kill'),board=(STEED,));self.play(g,'k54.kill',self.entity(g,STEED).id)
        self.play(g,'k54.kill',self.entity(g,STEED).id);self.assertEqual(g.state.players[1].board,[])
    def test_silence_removes_native_reborn_and_ordinary_enchantments(self):
        g=self.game(('k54.buff','k54.silence','k54.kill'),board=(STEED,));target=self.entity(g,STEED).id
        self.play(g,'k54.buff',target);self.play(g,'k54.silence',target);self.play(g,'k54.kill',target);self.assertEqual(g.state.players[1].board,[])
    def test_current_copy_has_its_own_native_policy_and_copied_enchantments(self):
        g=self.game(('k54.buff','k54.copy_minion','k54.kill'),board=(STEED,));target=self.entity(g,STEED).id
        self.play(g,'k54.buff',target);self.play(g,'k54.copy_minion',target);copy=g.state.players[1].board[-1]
        self.play(g,'k54.kill',copy);e=g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual((e.attack,e.health),(5,7));self.assertNotEqual(e.id,copy);self.portable(g)
    def test_native_policy_reinstalls_on_ordinary_bounce_reset(self):
        g=self.game(('k54.buff','k54.bounce','k54.kill'),board=(STEED,));target=self.entity(g,STEED).id
        self.play(g,'k54.buff',target);self.play(g,'k54.bounce',target);self.play(g,STEED);self.play(g,'k54.kill',target)
        self.assertEqual((self.entity(g,STEED).attack,self.entity(g,STEED).health),(2,3))
    def test_reborn_waiting_material_restores_original_policy_once(self):
        mode='reborn_wait';g=self.game(('k54.kill',),board=('k54.watch',STEED),mode=mode)
        self.play(g,'k54.kill',self.entity(g,STEED).id);other=self.portable(g,mode);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.entity(g,STEED).health,3);self.portable(g,mode)
    def test_native_policy_rejects_non_minions_missing_keyword_and_wrong_value(self):
        for card in(CardDefinition('bad','bad',CardType.SPELL,keywords=(Keyword.REBORN,),reborn_policy=POLICY),
                replace(self.r.card(STEED),keywords=()),replace(self.r.card(STEED),reborn_policy='invented')):
            with self.assertRaises(ValueError):self.r._validate_card(card)
    def test_old_null_policy_pin_is_stable_but_real_policy_is_signed(self):
        plain=self.r.card(PLAIN);value=asdict(plain);value.pop('reborn_policy');value.pop('hand_mirror');value.pop('native_condition');value.pop('dormant_board_full');value.pop('native_deathrattle')
        self.assertEqual(reviewed_definition_digest(plain),canonical_digest(value))
        self.assertNotEqual(reviewed_definition_digest(self.r.card(STEED)),reviewed_definition_digest(replace(self.r.card(STEED),reborn_policy=None)))
    def test_native_policy_snapshot_rejects_borrowed_source(self):
        g=self.game(board=(STEED,));saved=g.snapshot();e=self.entity(g,STEED)
        row=saved['state']['entities'][str(e.id)]
        next(x for x in row['abilities']if x['reborn_policy']is not None)['source_id']=self.hero(g)
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())
    def test_thrasher_without_previous_match_draws_without_local_bonus(self):
        g=self.game((THRASH,),deck=(FIRE,));self.play(g,THRASH);e=self.entity(g,FIRE,zone='hand');self.assertFalse(self.local(e))
        self.play(g,FIRE,self.hero(g,2));self.assertEqual(g.state.entities[self.hero(g,2)].health,24)
    def test_previous_own_beast_enchants_original_drawn_fire_spell(self):
        g=self.game(('k54.beast',THRASH),deck=(PLAIN,FIRE));self.kindred(g);s=g.state;original=next(i for i in s.players[1].deck if s.entities[i].card_id==FIRE)
        self.play(g,THRASH);e=g.state.entities[original];self.assertEqual(e.zone,Zone.HAND);self.assertEqual([a.spell_damage for a in self.local(e)],[2])
        self.play(g,FIRE,self.hero(g,2));self.assertEqual(g.state.entities[self.hero(g,2)].health,22);self.portable(g)
    def test_current_turn_beast_does_not_replace_previous_turn_requirement(self):
        g=self.game(('k54.beast',THRASH),deck=(FIRE,));self.play(g,'k54.beast');self.play(g,THRASH)
        self.assertFalse(self.local(self.entity(g,FIRE,zone='hand')))
    def test_literal_scenario_beast_board_is_not_a_played_kindred_fact(self):
        g=self.game((THRASH,),board=('k54.beast',),deck=(PLAIN,FIRE));self.cycle(g);self.play(g,THRASH)
        self.assertFalse(self.local(self.entity(g,FIRE,zone='hand')))
    def test_empty_fire_match_keeps_deck_and_rng_without_fatigue(self):
        g=self.game(('k54.beast',THRASH),deck=(PLAIN,PLAIN));self.kindred(g);before=g.snapshot();self.play(g,THRASH)
        self.assertEqual(g.snapshot()['rng_state'],before['rng_state']);self.assertEqual(len(g.state.draw_history),len(before['state']['draw_history']))
    def test_local_bonus_does_not_increase_global_board_spell_damage(self):
        g=self.game(('k54.grant',FIRE));self.play(g,'k54.grant');self.assertEqual(spell_bonus(g.state,1,g.registry),0)
    def test_other_physical_same_name_spell_does_not_receive_bonus(self):
        g=self.game(('k54.grant',FIRE,FIRE));self.play(g,'k54.grant');self.play(g,FIRE,self.hero(g,2));self.play(g,FIRE,self.hero(g,2))
        self.assertEqual(g.state.entities[self.hero(g,2)].health,16);self.assertEqual([len(c.local_spell_damage)for c in g.state.cast_history[-2:]],[1,0]);self.portable(g)
    def test_board_provider_stacks_with_local_spell_bonus(self):
        g=self.game(('k54.grant',FIRE),board=('k54.power',));self.play(g,'k54.grant');self.play(g,FIRE,self.hero(g,2))
        self.assertEqual(g.state.entities[self.hero(g,2)].health,21)
    def test_two_damage_operations_each_use_existing_spell_bonus_rules(self):
        g=self.game(('k54.grant','k54.waves'));self.play(g,'k54.grant');self.play(g,'k54.waves',self.hero(g,2))
        self.assertEqual(g.state.entities[self.hero(g,2)].health,24);self.assertEqual(len(g.state.cast_history[-1].local_spell_damage),1);self.portable(g)
    def test_random_split_uses_local_bonus_once_in_whole_budget(self):
        g=self.game(('k54.grant','k54.split'));self.play(g,'k54.grant');self.play(g,'k54.split')
        self.assertEqual(g.state.entities[self.hero(g,2)].health,25);self.portable(g)
    def test_granting_twice_stacks_two_distinct_original_abilities(self):
        g=self.game(('k54.grant','k54.grant',FIRE));self.play(g,'k54.grant');self.play(g,'k54.grant');self.play(g,FIRE,self.hero(g,2))
        self.assertEqual(g.state.entities[self.hero(g,2)].health,20);self.assertEqual(len(g.state.cast_history[-1].local_spell_damage),2)
    def test_current_and_base_spell_copies_follow_shared_attachment_material(self):
        g=self.game(('k54.grant',FIRE,'k54.copy_current','k54.copy_base'));self.play(g,'k54.grant');self.play(g,'k54.copy_current');self.play(g,'k54.copy_base');s=g.state
        rows=[s.entities[i]for i in s.players[1].hand if s.entities[i].card_id==FIRE]
        self.assertEqual([len(self.local(e))for e in rows],[1,1,0]);self.assertNotEqual(self.local(rows[0])[0].id,self.local(rows[1])[0].id);self.portable(g)
    def test_stale_hand_reference_cannot_enchant_same_id_in_deck(self):
        g=self.game(('k54.stale',FIRE));original=self.entity(g,FIRE,zone='hand').id;self.play(g,'k54.stale')
        self.assertEqual(g.state.entities[original].zone,Zone.DECK);self.assertFalse(self.local(g.state.entities[original]));self.portable(g)
    def test_drawn_automatic_fire_receives_bonus_before_its_payload(self):
        g=self.game(('k54.beast',THRASH),deck=(PLAIN,'k54.auto',PLAIN));self.kindred(g);self.play(g,THRASH)
        self.assertEqual(g.state.entities[self.hero(g,2)].health,27)
        rows=[c for c in g.state.cast_history if c.card_id=='k54.auto'];self.assertEqual(len(rows),1);self.assertEqual(rows[0].origin,'draw')
        self.assertEqual(len(rows[0].local_spell_damage),1);self.assertEqual([d.outcome for d in g.state.draw_history if d.player_id==1],['hand','cast','hand']);self.portable(g)
    def test_replacement_draw_does_not_gain_original_tutor_reward(self):
        g=self.game(('k54.beast',THRASH),deck=(PLAIN,'k54.auto',FIRE));self.kindred(g);self.play(g,THRASH)
        self.assertFalse(self.local(self.entity(g,FIRE,zone='hand')));self.portable(g)
    def test_draw_wait_can_restore_before_automatic_cast_without_losing_bonus(self):
        mode='draw_wait';g=self.game(('k54.beast',THRASH),deck=(PLAIN,'k54.auto',PLAIN),board=('k54.watch',),mode=mode)
        self.kindred(g);self.play(g,THRASH);other=self.portable(g,mode);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[self.hero(g,2)].health,27);self.portable(g,mode)
    def test_payload_wait_restores_complete_local_ability_material(self):
        mode='cast_wait';g=self.game(('k54.grant','k54.waves'),board=('k54.watch',),mode=mode);self.play(g,'k54.grant')
        self.play(g,'k54.waves',self.hero(g,2));other=self.portable(g,mode);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[self.hero(g,2)].health,24);self.portable(g,mode)
    def test_bad_payload_choice_rolls_back_to_original_wait_boundary(self):
        mode='cast_wait';g=self.game(('k54.grant','k54.waves'),board=('k54.watch',),mode=mode);self.play(g,'k54.grant');self.play(g,'k54.waves',self.hero(g,2));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(g.state.entities[self.hero(g,2)].health,24)
    def test_local_material_snapshot_rejects_future_or_borrowed_source(self):
        g=self.game(('k54.grant',FIRE));self.play(g,'k54.grant');self.play(g,FIRE,self.hero(g,2))
        for field,value in(('id',g.state.next_attachment_id),('source_id',999999)):
            saved=g.snapshot();saved['state']['cast_history'][-1]['local_spell_damage'][0][field]=value
            with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())
    def test_countered_physical_spell_claims_no_local_payload(self):
        g=self.game(('k54.grant',FIRE),other=('CORE_EX1_287',));self.play(g,'k54.grant');g.apply(EndTurn(1));self.play(g,'CORE_EX1_287',p=2);g.apply(EndTurn(2))
        self.play(g,FIRE,self.hero(g,2));cast=g.state.cast_history[-1];self.assertEqual(cast.failure,'countered');self.assertFalse(cast.local_spell_damage)
        self.assertEqual(g.state.entities[self.hero(g,2)].health,30);self.portable(g)
    def test_local_bonus_codec_checks_original_and_nonfuture_allocations(self):
        g=self.game((FIRE,));ref=CardReference.capture(self.entity(g,FIRE,zone='hand'));source=self.hero(g)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);effect=GrantStoredSpellDamage(ref,2,source)
        self.assertEqual(codec.decode(codec.encode(effect)),effect)
        for bad in(replace(effect,source_id=999999),replace(effect,card=replace(ref,zone_epoch=ref.zone_epoch+1))):
            with self.assertRaises(ValueError):codec.encode(bad)
    def test_complete_local_ability_disallows_unrelated_and_temporary_state(self):
        a=AbilityInstance(1,'spell_damage',source_id=1,spell_damage=2);validate_local_ability(a)
        for bad in(replace(a,expires_turn=2),replace(a,consumed=True),replace(a,origin='printed')):
            with self.assertRaises(ValueError):validate_local_ability(bad)
        with self.assertRaises(ValueError):replace(a,health=1)
    def test_hidden_draw_bonus_does_not_publish_card_identity_or_cast_proofs(self):
        g=self.game(('k54.beast',THRASH),deck=(PLAIN,FIRE));self.kindred(g);self.play(g,THRASH)
        other=json.dumps(g.for_player(2).observe(),ensure_ascii=False);self.assertNotIn(FIRE,other);self.assertNotIn('local_spell_damage',other)
        self.assertNotIn('stored_spell_damage_granted',json.dumps(g.for_player(2).events(),ensure_ascii=False));self.portable(g)
    def test_full_hand_burn_does_not_execute_the_enchanted_drawn_spell(self):
        mode='fill_hand';g=self.game(('k54.beast',THRASH),deck=(PLAIN,'k54.auto',PLAIN),board=('k54.watch',),mode=mode,hand_cap=3)
        self.kindred(g);self.play(g,THRASH);self.assertEqual(g.state.draw_history[-1].outcome,'burned')
        self.assertEqual(g.state.entities[self.hero(g,2)].health,30);self.assertFalse(any(c.card_id=='k54.auto'for c in g.state.cast_history));self.portable(g,mode)
    def test_non_damage_spell_does_not_pass_its_bonus_to_a_later_spell(self):
        g=self.game(('k54.grant','k54.armor',FIRE));self.play(g,'k54.grant');self.play(g,'k54.armor');self.play(g,FIRE,self.hero(g,2))
        self.assertEqual(g.state.entities[self.hero(g,2)].health,24);self.portable(g)
    def test_split_local_contribution_cannot_borrow_another_physical_spell(self):
        from hs_sim.engine.random_split_damage import validate_compact_facts
        g=self.game(('k54.grant','k54.split'));giver,_=self.play(g,'k54.grant');self.play(g,'k54.split')
        root=g.state.split_damage_history[-1];row=root.quote.contributions[0]
        other=type(row.allocation).capture(g.state,g.state.entities[giver])
        bad=replace(root,quote=replace(root.quote,contributions=(replace(row,allocation=other),)))
        with self.assertRaisesRegex(ValueError,'original local CAST'):validate_compact_facts(g.state,g.registry,bad)


if __name__=='__main__':unittest.main()
