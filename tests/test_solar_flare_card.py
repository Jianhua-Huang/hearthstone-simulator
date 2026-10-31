"""Solar Flare prices current Elementals with complete original tribe operands."""
from copy import deepcopy
from dataclasses import asdict,fields,replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import solar_flare_card as native
from hs_sim.engine import (BoardMinionCostSpec,CardClass,CardDefinition,CardType,Game,InteractableSpec,
    PlayCard,PlayerSetup,Rarity,ResolutionError,Scenario,SnapshotError,TriggerSpec)
from hs_sim.engine.card_conditions import UnknownCardFactError
from hs_sim.engine.costs import quote_cost,quote_generated_cost
from hs_sim.engine.effects import (AddCostModifier,ChangeControl,ChoiceOption,CopyMinion,Destroy,InvokeBehavior,
    ModifyCost,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.intrinsic_costs import (capture_intrinsic_stage,validate_intrinsic_history_prefix,
    validate_intrinsic_origin,validate_intrinsic_stage_fact)
from hs_sim.engine.interactables import InstallInteractable
from hs_sim.engine.model import CardMetadata,CostSpec,TargetSpec,TribeChangeSpec,Zone
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION,canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.tribes import ChangeMinionTribes,has_any_tribe
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

SOLAR=native.CARD;P='k607.'
NOOP,EL,PLAIN,ALL,UNKNOWN,DORMANT,INERT,POWER,ADD,SET,REMOVE,SILENCE,KILL,RETURN,GIVE,COPY,LOCAL,EXTERNAL,WAIT,KILLWAIT,FAIL,AUTO,PLACE=(
    P+s for s in('noop','elemental','plain','all','unknown','dormant','inert','power','add','set','remove','silence','kill','return','give',
    'copy','local','external','wait','killwait','fail','auto','place'))
META=CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=build_registry();r.register_behavior(NOOP,lambda c:())
    for cid,tribes,dormant in((EL,('elemental',),0),(PLAIN,(),0),(ALL,('all',),0),(UNKNOWN,None,0),(DORMANT,('elemental',),2),(POWER,('elemental',),0)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=8,dormant_turns=dormant,
            spell_damage=1 if cid==POWER else 0,metadata=replace(META,tribes=tribes)))
    r.register_card(CardDefinition(INERT,INERT,CardType.MINION,health=1,corpse_value=0,interactable=InteractableSpec(NOOP),
        metadata=replace(META,collectible=False,rarity=Rarity.NONE,tribes=('elemental',))))
    def change(c,op):return(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),
        TribeChangeSpec(op,('elemental',)),c.source_id),)
    r.register_behavior(ADD,lambda c:change(c,'add'));r.register_behavior(SET,lambda c:change(c,'set'));r.register_behavior(REMOVE,lambda c:change(c,'remove'))
    for cid,fn in((SILENCE,lambda c:(Silence(c.target_id),)),(KILL,lambda c:(Destroy(c.target_id,c.source_id),)),
            (RETURN,lambda c:(ReturnToHand(c.target_id),)),(GIVE,lambda c:(ChangeControl(c.target_id,3-c.player_id),)),
            (COPY,lambda c:(CopyMinion(c.target_id,c.player_id),))):r.register_behavior(cid,fn)
    r.register_behavior(LOCAL,lambda c:(ModifyCost(next(i for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==SOLAR),CostSpec(set_to=4),c.source_id),))
    r.register_behavior(EXTERNAL,lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-1,card_types=(CardType.SPELL,)),uses_remaining=1,source_id=c.source_id),))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,SOLAR,c.source_id),))
    r.register_behavior(PLACE,lambda c:(InstallInteractable(c.player_id,INERT,c.source_id),))
    def fault(c):raise ResolutionError('K607 deliberate reaction failure')
    r.register_behavior(P+'fault',fault)
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id)
        if source is None or source.card_id!=SOLAR:return ()
        if c.source.card_id==FAIL and e.kind=='damage_dealt':return(InvokeBehavior(P+'fault',c.source_id,c.player_id),)
        if c.source.card_id not in(WAIT,KILLWAIT)or e.kind!='card_committed':return ()
        targets=[c.state.entities[i]for i in c.state.players[c.player_id].board if i!=c.source_id and has_any_tribe(r,c.state.entities[i],('elemental',))]
        prefix=tuple(Destroy(e.id,c.source_id)for e in targets)if c.source.card_id==KILLWAIT else ()
        opts=[ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(InvokeBehavior(P+'fault',c.source_id,c.player_id),))]
        if targets and c.source.card_id==WAIT:
            opts.append(ChoiceOption('lose','Remove Elemental',(ChangeMinionTribes(MinionReference.capture(targets[0]),TribeChangeSpec('remove',('elemental',)),c.source_id),)))
        return (*prefix,RequestChoice(c.player_id,tuple(opts),c.source_id))
    r.register_behavior(P+'watch',watch)
    for cid,event in((WAIT,'card_committed'),(KILLWAIT,'card_committed'),(FAIL,'damage_dealt')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=30,metadata=META,triggers=(TriggerSpec(event,P+'watch'),)))
    targeted=(ADD,SET,REMOVE,SILENCE,KILL,RETURN,GIVE,COPY)
    for cid in(NOOP,*targeted,LOCAL,EXTERNAL,AUTO,PLACE):r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
        **({'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))}if cid in targeted else {})))
    r.validate();return r


class SolarFlareTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'

    def game(self,hand=(),*,board=(),enemy_board=(),player=1):
        setups=tuple(PlayerSetup('HERO_08',hand=hand if p==player else(),deck=(NOOP,)*6,
            board=board if p==player else enemy_board,mana=30,max_mana=30,mana_cap=30)for p in(1,2))
        return Game.from_scenario(Scenario(setups,active_player=player,seed=607),registry())

    def paid(self,g,cid=SOLAR,target=None,p=1):
        entity=self.entity(g,cid,p);amount=quote_cost(g.state,g.registry,entity).amount;mana=g.state.players[p].mana
        source=self.play(g,cid,target,p);self.assertEqual(g.state.players[p].mana,mana-amount)
        self.assertEqual((g.state.play_history[-1].card_id,g.state.play_history[-1].cost),(cid,amount));return source

    def cost(self,g,p=1):return quote_cost(g.state,g.registry,self.entity(g,SOLAR,p)).amount

    def stage(self,g,p=1):return capture_intrinsic_stage(g.state,g.registry,p,SOLAR,5)

    def hero(self,g,p):return g.state.entities[g.state.players[p].hero_id]

    def test_full_source_two_primary_faces_and_finite_native_profile_without_definition_fields(self):
        data=native.load_batch();raw=data['cards'][0]['record']
        for obs in data['official_observations']:batch.check_face(raw,obs['face'],obs['locale'])
        self.assertEqual(len(data['official_observations']),2);card=registry().card(SOLAR)
        self.assertEqual((card.cost,card.spell_school.value,card.board_minion_cost.profile_id),(5,'fire',native.PROFILE))
        self.assertEqual([f.name for f in fields(BoardMinionCostSpec)],['scope','profile_id']);self.assertEqual(card.board_minion_cost.tribes_any,('elemental',))
        self.assertEqual(BoardMinionCostSpec().tribes_any,());self.assertEqual(native.COLLECTIBLE_ROOTS,())
        for scope in('all','enemy'):
            with self.assertRaises(ValueError):BoardMinionCostSpec(scope,native.PROFILE)
        with self.assertRaises(ValueError):BoardMinionCostSpec('friendly','invented.tribes')

    def test_actual_friendly_elementals_not_other_minions_or_enemy_elementals_and_both_seat_payments(self):
        for p in(1,2):
            g=self.game((SOLAR,),board=(EL,PLAIN,ALL),enemy_board=(EL,PLAIN),player=p)
            self.assertEqual(self.cost(g,p),3);self.assertEqual(quote_generated_cost(g.state,g.registry,p,SOLAR).amount,3)
            self.paid(g,p=p);self.assertEqual(self.hero(g,3-p).health,28);self.assertEqual(self.hero(g,p).health,30)
            self.assertEqual([g.state.entities[i].health for i in g.state.players[3-p].board],[6,6])
            self.assertEqual([g.state.entities[i].health for i in g.state.players[p].board],[8,8,8])

    def test_empty_board_printed_cost_and_zero_floor_queries_are_pure(self):
        for board,cost in(((),5),((EL,)*6,0)):
            g=self.game((SOLAR,),board=board);saved=g.snapshot()
            for _ in range(2):
                self.assertEqual(self.cost(g),cost);self.assertEqual(quote_generated_cost(g.state,g.registry,1,SOLAR).amount,cost)
                validate_intrinsic_stage_fact(g.registry,self.stage(g))
            self.assertEqual(g.snapshot(),saved);self.assertEqual(self.entity(g,SOLAR).base_cost,5)

    def test_dormant_elementals_count_by_existing_residence_policy_and_inert_objects_do_not(self):
        g=self.game((SOLAR,PLACE),board=(EL,DORMANT,PLAIN));self.paid(g,PLACE);self.assertEqual(self.cost(g),3)
        fact=self.stage(g).board_minions;self.assertEqual([r.card_id for r in fact.boards[0]],[EL,DORMANT,PLAIN,INERT])
        self.assertIsNone(fact.boards[0][3].tribe_changes)

    def test_current_added_tribe_changes_price_and_silence_restores_printed_identity(self):
        g=self.game((SOLAR,ADD,SILENCE),board=(PLAIN,));target=g.state.players[1].board[0]
        self.assertEqual(self.cost(g),5);self.paid(g,ADD,target);self.assertEqual(self.cost(g),4)
        fact=self.stage(g).board_minions;self.assertEqual(len(fact.boards[0][0].tribe_changes),1)
        self.paid(g,SILENCE,target);self.assertEqual(self.cost(g),5)

    def test_all_tribe_exclusion_and_explicit_set_use_shared_current_tribe_semantics(self):
        g=self.game((SOLAR,REMOVE,SET),board=(ALL,));target=g.state.players[1].board[0]
        self.assertEqual(self.cost(g),4);self.paid(g,REMOVE,target);self.assertEqual(self.cost(g),5)
        self.paid(g,SET,target);self.assertEqual(self.cost(g),4)

    def test_copied_current_tribe_changes_have_distinct_physical_operands_and_both_count(self):
        g=self.game((SOLAR,ADD,COPY),board=(PLAIN,));target=g.state.players[1].board[0];self.paid(g,ADD,target);self.paid(g,COPY,target)
        fact=self.stage(g).board_minions;self.assertEqual(self.cost(g),3)
        ids=[r.tribe_changes[0].id for r in fact.boards[0]];self.assertEqual(len(set(ids)),2)

    def test_control_transfer_return_and_actual_death_recompute_current_quotes_without_cost_cache(self):
        for effect in(GIVE,RETURN,KILL):
            g=self.game((SOLAR,effect),board=(EL,));target=g.state.players[1].board[0];self.assertEqual(self.cost(g),4)
            self.paid(g,effect,target);self.assertEqual(self.cost(g),5);self.assertEqual(self.entity(g,SOLAR).base_cost,5)

    def test_unknown_relevant_identity_fails_even_after_zero_floor_and_complete_set_can_resolve_it(self):
        g=self.game((SET,),board=(UNKNOWN,));saved=g.snapshot()
        with self.assertRaises(UnknownCardFactError):quote_generated_cost(g.state,g.registry,1,SOLAR)
        self.assertEqual(g.snapshot(),saved);self.paid(g,SET,g.state.players[1].board[0])
        self.assertEqual(quote_generated_cost(g.state,g.registry,1,SOLAR).amount,4)
        g=self.game(board=(EL,)*5+(UNKNOWN,))
        with self.assertRaises(UnknownCardFactError):quote_generated_cost(g.state,g.registry,1,SOLAR)

    def test_unselected_enemy_unknown_tribes_do_not_invent_unneeded_operands_but_all_faces_are_retained(self):
        g=self.game((SOLAR,),board=(EL,),enemy_board=(UNKNOWN,));self.assertEqual(self.cost(g),4)
        fact=self.stage(g).board_minions;self.assertEqual(len(fact.boards[1]),1);self.assertIsNone(fact.boards[1][0].tribe_changes)

    def test_intrinsic_quantity_precedes_local_assignment_external_discount_and_actual_payment(self):
        g=self.game((SOLAR,LOCAL,EXTERNAL),board=(EL,EL));self.assertEqual(self.cost(g),3)
        self.paid(g,LOCAL);self.assertEqual(self.cost(g),4);self.paid(g,EXTERNAL);self.assertEqual(self.cost(g),3)
        self.assertEqual(quote_generated_cost(g.state,g.registry,1,SOLAR,cost=CostSpec(set_to=4)).amount,3)
        self.paid(g);self.assertEqual(g.state.players[1].mana,27)

    def test_player_display_actions_and_submission_share_current_filtered_quote(self):
        g=self.game((SOLAR,),board=(EL,EL));port=g.for_player(1);listing=port.legal_actions()
        card=listing['observation']['players'][0]['hand'][0];self.assertEqual(card['cost']['amount'],3)
        action=next(a for a in listing['actions']if a['type']=='play_card'and a['card']==card['ref'])
        self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted']);self.assertEqual(g.state.players[1].mana,27)

    def test_original_tribe_fact_survives_later_silence_as_history_but_does_not_match_new_quote_window(self):
        g=self.game((SOLAR,ADD,SILENCE),board=(PLAIN,));target=g.state.players[1].board[0];self.paid(g,ADD,target)
        original=self.stage(g);validate_intrinsic_origin(original,g.state,g.registry);self.paid(g,SILENCE,target)
        validate_intrinsic_stage_fact(g.registry,original);validate_intrinsic_history_prefix(original,g.state,g.registry)
        self.assertEqual((original.amount,self.cost(g)),(4,5))
        with self.assertRaises(ValueError):validate_intrinsic_origin(original,g.state,g.registry)

    def test_complete_original_quote_rejects_internally_consistent_omitted_tribe_attachment(self):
        g=self.game((SOLAR,ADD),board=(PLAIN,));self.paid(g,ADD,g.state.players[1].board[0]);state=g.state;stage=self.stage(g);fact=stage.board_minions
        row=replace(fact.boards[0][0],tribe_changes=());bad=replace(fact,boards=((row,),fact.boards[1]),quantity=0,after=5)
        forged=replace(stage,board_minions=bad,amount=5);validate_intrinsic_stage_fact(g.registry,forged)
        with self.assertRaisesRegex(ValueError,'original quotation'):validate_intrinsic_origin(forged,state,g.registry)

    def test_missing_selected_tribes_or_unselected_extra_operands_are_rejected(self):
        g=self.game((SOLAR,),board=(EL,),enemy_board=(PLAIN,));stage=self.stage(g);fact=stage.board_minions
        missing=replace(fact.boards[0][0],tribe_changes=None)
        with self.assertRaisesRegex(ValueError,'tribe operands'):validate_intrinsic_stage_fact(g.registry,
            replace(stage,board_minions=replace(fact,boards=((missing,),fact.boards[1]))))
        extra=replace(fact.boards[1][0],tribe_changes=())
        with self.assertRaisesRegex(ValueError,'tribe operands'):validate_intrinsic_stage_fact(g.registry,
            replace(stage,board_minions=replace(fact,boards=(fact.boards[0],(extra,)))))

    def test_tribe_operand_future_allocation_missing_clock_and_duplicate_attachment_are_rejected(self):
        g=self.game((SOLAR,ADD,ADD),board=(PLAIN,PLAIN));self.paid(g,ADD,g.state.players[1].board[0]);self.paid(g,ADD,g.state.players[1].board[1])
        stage=self.stage(g);fact=stage.board_minions;first,second=fact.boards[0]
        future=replace(first.tribe_changes[0],id=fact.next_attachment_id)
        with self.assertRaises(ValueError):replace(fact,boards=((replace(first,tribe_changes=(future,)),second),fact.boards[1]))
        future_source=replace(first.tribe_changes[0],source_id=fact.next_entity_id)
        with self.assertRaises(ValueError):replace(fact,boards=((replace(first,tribe_changes=(future_source,)),second),fact.boards[1]))
        with self.assertRaises(ValueError):replace(fact,next_attachment_id=None)
        with self.assertRaises(ValueError):replace(fact,next_attachment_id=True)
        with self.assertRaises(ValueError):replace(fact,boards=((first,replace(second,tribe_changes=first.tribe_changes)),fact.boards[1]))
        late=replace(fact,next_attachment_id=g.state.next_attachment_id+1)
        with self.assertRaisesRegex(ValueError,'allocation prefix'):validate_intrinsic_history_prefix(replace(stage,board_minions=late),g.state,g.registry)

    def test_wait_after_payment_keeps_original_changed_tribe_rows_and_choice_cannot_reprice(self):
        g=self.game((SOLAR,ADD),board=(PLAIN,WAIT));self.paid(g,ADD,g.state.players[1].board[0]);self.paid(g)
        self.assertEqual(g.state.players[1].mana,26);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'lose');self.choose(other,'lose')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.players[1].mana,26)
        self.assertEqual(quote_generated_cost(g.state,g.registry,1,SOLAR).amount,5);self.assertEqual(self.hero(g,2).health,28)

    def test_original_attached_tribe_source_can_die_before_wait_and_restore_without_repayment(self):
        g=self.game((SOLAR,ADD),board=(PLAIN,KILLWAIT));target=g.state.players[1].board[0];self.paid(g,ADD,target);self.paid(g)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);other=self.portable(g)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.players[1].mana,26)
        self.assertEqual(self.hero(g,2).health,28)

    def test_spell_damage_affects_each_enemy_packet_once_and_free_automatic_cast_does_not_pay_quote(self):
        g=self.game((SOLAR,),board=(POWER,),enemy_board=(PLAIN,PLAIN));self.paid(g)
        self.assertEqual(self.hero(g,2).health,27);self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[5,5])
        g=self.game((AUTO,),board=(EL,),enemy_board=(PLAIN,));self.paid(g,AUTO)
        self.assertEqual(g.state.players[1].mana,30);self.assertEqual(self.hero(g,2).health,28);self.assertEqual(len(g.state.play_history),1)

    def test_late_damage_reaction_failure_rolls_back_payment_entities_rng_and_original_operands(self):
        g=self.game((SOLAR,ADD),board=(PLAIN,FAIL),enemy_board=(PLAIN,));self.paid(g,ADD,g.state.players[1].board[0]);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,SOLAR)
        self.assertEqual(g.snapshot(),saved)

    def test_new_row_fields_are_strict_and_schema608_is_not_silently_upgraded(self):
        g=self.game((SOLAR,ADD),board=(PLAIN,WAIT));self.paid(g,ADD,g.state.players[1].board[0]);self.paid(g)
        self.assertEqual(SNAPSHOT_SCHEMA_VERSION,679)
        data=g.snapshot();data['schema_version']=608
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,registry('normal','independent-reader'))
        data=g.snapshot()
        def find(value):
            if isinstance(value,dict):
                if isinstance(value.get('spec'),dict)and value['spec'].get('profile_id')==native.PROFILE and 'boards'in value:return value
                for item in value.values():
                    found=find(item)
                    if found is not None:return found
            elif isinstance(value,list):
                for item in value:
                    found=find(item)
                    if found is not None:return found
        fact=find(data);self.assertIsNotNone(fact);del fact['boards'][0][0]['tribe_changes']
        data['state_hash']=canonical_hash({k:v for k,v in data.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,registry('normal','independent-reader'))

    def test_private_original_tribe_operands_and_clocks_are_not_player_fields(self):
        g=self.game((SOLAR,ADD),board=(PLAIN,));self.paid(g,ADD,g.state.players[1].board[0]);view=json.dumps(g.for_player(1).observe())
        for token in('"tribe_changes"','"next_attachment_id"','"board_minions"','"resolution_frame"','"state_hash"'):self.assertNotIn(token,view)

    def test_bad_source_cost_rejected_before_partial_registration(self):
        data=deepcopy(native.load_batch());data['cards'][0]['record']['cost']=0
        r=batch.registration_prefix(build_registry,'hs_sim.cards.solar_flare_card.register_solar_flare_card',native.register_solar_flare_card)
        before=(dict(r.cards),dict(r.pool_cards),dict(r._behaviors))
        with patch.object(native,'load_batch',return_value=data):
            with self.assertRaises(TargetValidationError):native.register_solar_flare_card(r)
        self.assertEqual((r.cards,r.pool_cards,r._behaviors),before)


if __name__=='__main__':unittest.main()
