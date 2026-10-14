"""Native recipient selection reuses exact current card IDs, never names."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, AuraSpec, CardClass, CardDefinition, CardType, EndTurn,
    Game, IllegalAction, Keyword, KeywordAuraSpec, PlayCard, PlayerSetup, Rarity, Registry,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.keyword_auras import GrantKeywordAura, validate_carrier as validate_keyword_carrier
from hs_sim.engine.model import AbilityInstance
from hs_sim.engine.registry import RuleContext, UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.stat_auras import validate_carrier as validate_stat_carrier
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

TRAINER='AT_075'; RECRUITS=('CS2_101t','CS2_101t2')
STAT=AuraSpec(attack=2,card_ids=RECRUITS)
KEYWORD=KeywordAuraSpec(Keyword.TAUNT,'friendly_minions',card_ids=RECRUITS)
PATH=Path(__file__).resolve().parents[1]/'data/support/card-identity-aura-basics.json'
PIN='a38815749006752df3adcedd1fdc05dd9a321fd400f65b83d094cb486d823c65'


def evidence():
    support=json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support)!=PIN:raise ValueError('Card identity aura evidence changed')
    for row in support['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Raw evidence changed')
    return {r['id']:r['data'] for r in support['records']}


def registry():
    r=Registry('isolated-card-identity-aura-basics-v1');raw=evidence()
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata()))
    row=raw[TRAINER]
    r.register_card(CardDefinition(TRAINER,row['name'],CardType.MINION,cost=row['cost'],
        attack=row['attack'],health=row['health'],auras=(STAT,),keyword_auras=(KEYWORD,),metadata=metadata(CardClass.PALADIN)))
    for cid in RECRUITS:
        row=raw[cid]
        r.register_card(CardDefinition(cid,row['name'],CardType.MINION,cost=row['cost'],
            attack=row['attack'],health=row['health'],metadata=metadata(CardClass.PALADIN,collectible=False,tribes=(),rarity=Rarity.FREE)))
    r.register_card(CardDefinition('same-name',raw[RECRUITS[0]]['name'],CardType.MINION,
        attack=1,health=1,metadata=metadata(CardClass.PALADIN,tribes=None)))
    r.register_card(CardDefinition('plain','Plain',CardType.MINION,attack=2,health=12,metadata=metadata()))
    def source(c):return next(i for i in c.state.players[1].board if c.state.entities[i].card_id==TRAINER)
    def fail(c):raise ValueError('Fixture failure')
    r.register_behavior('fail',fail)
    def pause(c):
        src=source(c);recipient=next(i for i in c.state.players[1].board if c.state.entities[i].card_id in RECRUITS)
        return (RequestChoice(1,(
            ChoiceOption('silence','Silence source',(Silence(src),)),
            ChoiceOption('change','Transform recipient',(Transform(recipient,'plain'),)),
            ChoiceOption('fault','Change and fail',(Transform(recipient,'plain'),InvokeBehavior('fail',source_id=c.source_id,player_id=1))),
        ),c.source_id),)
    r.register_behavior('wait',pause)
    r.register_card(CardDefinition('watch','Watch',CardType.MINION,health=12,
        triggers=(TriggerSpec('attack_declared','wait'),),metadata=metadata()))
    targeted={
        'silence':lambda c:(Silence(c.target_id),),
        'transform-out':lambda c:(Transform(c.target_id,'plain'),),
        'transform-in':lambda c:(Transform(c.target_id,RECRUITS[1]),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'copy':lambda c:(CopyMinion(c.target_id,1),),
        'base-copy':lambda c:(CopyMinion(c.target_id,1,mode='base'),),
        'transfer':lambda c:(ChangeControl(c.target_id,2),),
        'sleep':lambda c:(MakeDormant(c.target_id,None),),
        'kill':lambda c:(Destroy(c.target_id),),
        'fault':lambda c:(Silence(c.target_id),InvokeBehavior('fail',source_id=c.source_id,player_id=1)),
    }
    scripts={
        'wait':pause,
        'wake':lambda c:(AwakenMinion(next(i for i in c.state.players[1].board if c.state.entities[i].dormancy is not None)),),
        'summon':lambda c:(Summon(1,RECRUITS[1]),),
    }
    for cid,body in {**targeted,**scripts}.items():
        if cid!='wait':r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,requires_target=cid in targeted,metadata=metadata()))
    return r


class CardIdentityAuraBasicsTests(unittest.TestCase):
    def game(self,board=(TRAINER,*RECRUITS,'same-name'),hand=(),enemy=('plain',),enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*5,mana=10,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,board=enemy,deck=('plain',)*5,mana=10,max_mana=10),
        ),seed=52),registry())
    def source(self,g):return next(i for i in g.state.players[1].board if g.state.entities[i].card_id==TRAINER)
    def recipient(self,g):return next(i for i in g.state.players[1].board if g.state.entities[i].card_id==RECRUITS[0])
    def play(self,g,cid,target=None):
        p=g.state.active_player;eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid,target if g.registry.card(cid).requires_target else None));return eid
    def choose(self,g,key='silence'):
        c=g.state.pending_choice;return g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def stats(self,g,eid,attack=3,taunt=True):
        e=g.state.entities[eid];self.assertEqual(e.attack,attack);self.assertEqual(Keyword.TAUNT in e.keywords,taunt)
    def check(self,g):
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,registry()).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap);self.assertEqual(replay(build_replay(g),registry()).snapshot(),snap)
    def rehash(self,s):
        keys=('ruleset','registry_fingerprint','mechanics_version','state','rng_state','resolution_frame',
              'rewind_session','match_setup','generation_context','information')
        s['state_hash']=canonical_hash({key:s[key] for key in keys});return s

    def test_full_raw_native_source_and_two_explicit_token_ids(self):
        raw=evidence();r=registry()
        self.assertEqual((raw[TRAINER]['dbf_id'],raw[TRAINER]['cost'],raw[TRAINER]['attack'],raw[TRAINER]['health']),(2515,3,3,4))
        self.assertEqual([raw[c]['dbf_id'] for c in RECRUITS],[1652,105917])
        self.assertEqual([r.card(c).metadata.rarity for c in RECRUITS],[Rarity.FREE]*2)
        self.assertEqual((r.card(TRAINER).auras,r.card(TRAINER).keyword_auras),((STAT,),(KEYWORD,)))
        self.assertNotIn('CORE_AT_075',r.cards)

    def test_two_registered_id_recipients_match_without_using_names_or_tribes(self):
        g=self.game();ids=g.state.players[1].board
        for eid in ids[1:3]:self.stats(g,eid)
        self.stats(g,ids[3],1,False);self.stats(g,ids[0],3,False)
        self.assertIsNone(g.registry.card('same-name').metadata.tribes);self.check(g)

    def test_new_hand_recipient_acquires_aura_only_on_board(self):
        g=self.game(hand=(RECRUITS[0],));eid=g.state.players[1].hand[0];self.stats(g,eid,1,False)
        self.play(g,RECRUITS[0]);self.stats(g,eid);self.check(g)

    def test_summoned_alias_uses_same_recipient_filter(self):
        g=self.game(board=(TRAINER,),hand=('summon',));self.play(g,'summon')
        self.stats(g,g.state.players[1].board[-1]);self.check(g)

    def test_multiple_real_sources_stack_stats_and_union_taunt(self):
        g=self.game(board=(TRAINER,TRAINER,RECRUITS[0]),hand=('silence',));recipient=self.recipient(g)
        self.stats(g,recipient,5);self.play(g,'silence',g.state.players[1].board[0]);self.stats(g,recipient,3);self.check(g)

    def test_source_silence_removes_both_native_contributions(self):
        g=self.game(hand=('silence',));self.play(g,'silence',self.source(g))
        for eid in g.state.players[1].board[1:3]:self.stats(g,eid,1,False)
        self.check(g)

    def test_recipient_silence_keeps_external_aura(self):
        g=self.game(hand=('silence',));eid=self.recipient(g);self.play(g,'silence',eid);self.stats(g,eid);self.check(g)

    def test_transform_matches_current_face_then_restores_other_explicit_id(self):
        g=self.game(hand=('transform-out','transform-in'));eid=self.recipient(g)
        self.play(g,'transform-out',eid);self.stats(g,eid,2,False)
        self.play(g,'transform-in',eid);self.stats(g,eid);self.check(g)

    def test_current_and_base_recipient_copies_do_not_copy_aura_as_intrinsic_bonus(self):
        for cid in ('copy','base-copy'):
            with self.subTest(cid=cid):
                g=self.game(hand=(cid,));self.play(g,cid,self.recipient(g));self.stats(g,g.state.players[1].board[-1]);self.check(g)

    def test_current_and_base_source_copies_preserve_complete_native_selector(self):
        for cid in ('copy','base-copy'):
            with self.subTest(cid=cid):
                g=self.game(hand=(cid,));self.play(g,cid,self.source(g));self.stats(g,self.recipient(g),5);self.check(g)

    def test_source_return_and_replay_reinstalls_native_selection(self):
        g=self.game(hand=('bounce',));source=self.source(g);recipient=self.recipient(g)
        self.play(g,'bounce',source);self.stats(g,recipient,1,False)
        self.play(g,TRAINER);self.stats(g,recipient);self.check(g)

    def test_recipient_return_and_replay_recalculates_board_aura(self):
        g=self.game(hand=('bounce',));eid=self.recipient(g);self.play(g,'bounce',eid);self.stats(g,eid,1,False)
        self.play(g,RECRUITS[0]);self.stats(g,eid);self.check(g)

    def test_source_control_transfer_moves_recipient_population(self):
        g=self.game(hand=('transfer',),enemy=(RECRUITS[1],'plain'));recipient=self.recipient(g);enemy=g.state.players[2].board[0]
        self.play(g,'transfer',self.source(g));self.stats(g,recipient,1,False);self.stats(g,enemy);self.check(g)

    def test_recipient_control_transfer_loses_old_controller_aura(self):
        g=self.game(hand=('transfer',));eid=self.recipient(g);self.play(g,'transfer',eid);self.stats(g,eid,1,False);self.check(g)

    def test_dormant_source_and_recipient_pause_and_resume_existing_aura(self):
        for role in ('source','recipient'):
            with self.subTest(role=role):
                g=self.game(hand=('sleep','wake'));eid=self.source(g) if role=='source' else self.recipient(g)
                self.play(g,'sleep',eid);self.stats(g,self.recipient(g),1,False)
                self.play(g,'wake');self.stats(g,self.recipient(g));self.check(g)

    def test_source_death_removes_aura_and_preserves_complete_native_death_record(self):
        g=self.game(hand=('kill',));self.play(g,'kill',self.source(g));self.stats(g,self.recipient(g),1,False)
        record=next(r for r in g.state.death_history if r.card_id==TRAINER)
        self.assertEqual(next(a for a in record.abilities if a.kind=='aura').aura_card_ids,RECRUITS)
        self.assertEqual(next(a for a in record.abilities if a.kind=='keyword_aura').keyword_aura.card_ids,RECRUITS);self.check(g)

    def test_real_taunt_aura_restricts_enemy_attack_targets(self):
        g=self.game();hero=g.state.players[1].hero_id;enemy=g.state.players[2].board[0];g.apply(EndTurn(1))
        with self.assertRaises(IllegalAction):g.apply(Attack(2,enemy,hero))
        recipient=g.state.players[1].board[1];g.apply(Attack(2,enemy,recipient));self.check(g)

    def test_waiting_spell_restores_original_frame_and_uses_resumed_native_selection(self):
        g=self.game(hand=('wait',));self.play(g,'wait');self.check(g);restored=Game.from_snapshot(g.snapshot(),registry())
        self.choose(g);self.choose(restored);self.stats(g,self.recipient(g),1,False)
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_actual_attack_pause_can_change_current_recipient_identity(self):
        g=self.game(board=(TRAINER,*RECRUITS,'watch'));eid=self.recipient(g)
        g.apply(Attack(1,self.source(g),g.state.players[2].board[0]));self.check(g)
        self.choose(g,'change');self.stats(g,eid,2,False);self.check(g)

    def test_immediate_and_waiting_failure_roll_back_aura_and_identity(self):
        g=self.game(hand=('fault','wait'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'fault',self.source(g))
        self.assertEqual(g.snapshot(),before);self.play(g,'wait');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g,'change');self.check(g)

    def test_ids_are_unique_immutable_and_native_board_scopes_are_explicit(self):
        for value in (None,[],[RECRUITS[0]],RECRUITS[0],(True,),('',),RECRUITS+RECRUITS):
            for spec in (STAT,KEYWORD):
                with self.subTest(value=value,spec=spec),self.assertRaises(ValueError):replace(spec,card_ids=value)
        for spec in (STAT,KEYWORD):
            for fields in ({'adjacent_only':True},{'target':'self'},{'tribes_any':('beast',)}):
                with self.subTest(fields=fields,spec=spec),self.assertRaises(ValueError):replace(spec,**fields)
        for fields in ({'attack':True},{'health':-1},{'include_self':1}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):replace(STAT,**fields)

    def test_unknown_and_nonminion_ids_fail_at_registry_freeze(self):
        for target in ('missing','hero'):
            for kind in ('stat','keyword'):
                r=Registry('bad');r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=30))
                kwargs={'auras':(replace(STAT,card_ids=(target,)),)} if kind=='stat' else {'keyword_auras':(replace(KEYWORD,card_ids=(target,)),)}
                r.register_card(CardDefinition('source','Source',CardType.MINION,health=4,**kwargs))
                with self.subTest(target=target,kind=kind),self.assertRaises((ValueError,UnsupportedDefinitionError)):r.freeze()

    def test_native_instances_reject_optional_grants_and_other_ability_payloads(self):
        stat=AbilityInstance(1,'aura',source_id=2,origin='printed',attack=2,aura_card_ids=RECRUITS)
        key=AbilityInstance(2,'keyword_aura',source_id=2,origin='printed',keyword_aura=KEYWORD)
        for a in (stat,key):
            for fields in ({'origin':'granted'},{'source_id':None},{'consumed':True},{'expires_turn':1},{'remove_on_silence':False},{'magnetic_id':3}):
                with self.subTest(a=a,fields=fields),self.assertRaises(ValueError):replace(a,**fields)
        with self.assertRaises(ValueError):AbilityInstance(3,'spell_damage',spell_damage=1,aura_card_ids=RECRUITS)
        with self.assertRaises(ValueError):GrantKeywordAura(1,KEYWORD)

    def test_complete_native_selector_cannot_be_cleared_changed_or_duplicated(self):
        g=self.game();source=g.state.entities[self.source(g)]
        for a in source.abilities:
            if a.kind=='aura':
                for rows in ((replace(a,aura_card_ids=()),),(replace(a,aura_card_ids=RECRUITS[:1]),),(a,replace(a,id=999))):
                    with self.subTest(rows=rows),self.assertRaises(ValueError):validate_stat_carrier(g.registry,TRAINER,CardType.MINION,rows)
            elif a.kind=='keyword_aura':
                for rows in ((replace(a,keyword_aura=replace(KEYWORD,card_ids=())),),(a,replace(a,id=999))):
                    with self.subTest(rows=rows),self.assertRaises(ValueError):validate_keyword_carrier(g.registry,TRAINER,CardType.MINION,rows)

    def test_snapshot_rejects_missing_or_false_native_selector_after_rehash(self):
        g=self.game();source=self.source(g)
        for key in ('stat','keyword'):
            snap=g.snapshot();a=next(a for a in snap['state']['entities'][str(source)]['abilities'] if a['kind']==('aura' if key=='stat' else 'keyword_aura'))
            if key=='stat':del a['aura_card_ids']
            else:a['keyword_aura']['card_ids']=[]
            with self.subTest(key=key),self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(snap),registry())

    def test_captured_rule_context_rejects_changed_native_identity_declaration(self):
        g=self.game();ctx=RuleContext(g.state,self.source(g),1);codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        decoded=codec.decode(codec.encode(ctx));self.assertEqual(decoded.state.entities[self.recipient(g)].attack,3)
        state=deepcopy(ctx.state);source=state.entities[self.source(g)]
        source.abilities=[replace(a,aura_card_ids=()) if a.kind=='aura' else a for a in source.abilities]
        with self.assertRaises(ValueError):codec.decode(codec.encode(replace(ctx,state=state)))

    def test_player_queries_are_pure_and_keep_hidden_hand_private(self):
        g=self.game(hand=('bounce',),enemy_hand=('transform-out',));before=g.snapshot()
        for p in (1,2):
            for _ in range(2):
                text=json.dumps((g.for_player(p).observe(),g.for_player(p).legal_actions()))
                for key in ('abilities','aura_card_ids','work_queue','rng_state'):self.assertNotIn('"'+key+'"',text)
                if p==1:self.assertNotIn('transform-out',text)
                else:self.assertIn('transform-out',text)
        self.assertEqual(g.snapshot(),before)

    def test_current_schema_rejects_previous_and_future_versions(self):
        g=self.game();self.assertEqual(g.snapshot()['schema_version'],265)
        for version in (190,217,True):
            snap=g.snapshot();snap['schema_version']=version
            with self.assertRaises(SnapshotError):Game.from_snapshot(snap,registry())
