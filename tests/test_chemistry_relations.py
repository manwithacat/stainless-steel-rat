import numpy as np,pytest
from ssr.tasks import relations as R


def test_mask_g_block_targets_signed_words_and_corruption():
    w=np.zeros((80,10),dtype=np.int64);a=np.arange(len(w))
    w[:,5]=a&1
    r=R.parse('1 | 0:0 | 1')
    assert R.check(w,r)['status']=='CONSTRAINTS_HOLD'
    w[4,5]^=1
    report=R.check(w,r)
    assert report['violated_relation_rows']==1 and report['relations'][0]['first_addresses']==[4]
    spec=R.parse('1 | 0:0 | G/1/5')[0]['target']
    w[:,5]=[(int(x)&1)^((5>>(int(x)>>4))&1) for x in a]
    assert R.check(w,[dict(loader=1,outputs=[[0,0]],target=spec)])['status']=='CONSTRAINTS_HOLD'
    w[w==1]=-1 # same low bit under signed7bit representation
    assert R.check(w,[dict(loader=1,outputs=[[0,0]],target=spec)])['status']=='CONSTRAINTS_HOLD'


def test_f_is_seeded_low_xor_block_and_b_has_explicit_zone():
    a=np.arange(128);spec=R.parse('1 | 0:0 | F:17')[0]['target']
    rng=np.random.default_rng([17,5]);f=rng.integers(0,2,16);g=rng.integers(0,2,128)
    assert np.array_equal(R.target(spec,a),f[a%16]^g[a//16])
    b=R.parse('1 | 0:0 | B:5')[0]['target']
    assert R.target(b,np.array([0,16,32,48,64])).tolist()==[1,0,1,0,0]


def test_width_alias_address_and_unknown_target_refusals():
    for text in ['1|0:7|0','1|0:0 0:0|0','1|0:0|G/1','1|0:0|Q/1','1|0:0|B:16']:
        with pytest.raises(ValueError):R.parse(text)
    r=R.parse('1|0:0|0')
    w=np.zeros((2,10),dtype=np.int64);w[0,0]=128
    with pytest.raises(ValueError,match='width'):R.check(w,r)
    w[:]=0
    with pytest.raises(ValueError,match='unique'):R.check(w,r,addresses=np.array([0,0]))
    with pytest.raises(ValueError,match='outside'):R.check(w,r,addresses=np.array([0,2048]))


def test_cli_binds_truth_and_relation_files_and_preserves_failures(tmp_path):
    from ssr.tasks import cli,source
    from argparse import Namespace
    import json
    words=tmp_path/'words.npz';np.savez(words,angle_words=np.zeros((8,10),dtype=np.int64))
    rel=tmp_path/'rel.txt';rel.write_text('1 | 0:0 | 0\n')
    a=Namespace(words=str(words),relations=str(rel),word_bits=7,out=str(tmp_path/'proof'))
    result=cli.chemistry_relations(a)
    assert result['status']=='CONSTRAINTS_HOLD' and result['relations_sha256']==source.sha(rel)
    assert result['task_admission']=='NOT_RUN'
    with pytest.raises(FileExistsError):cli.chemistry_relations(a)
    a.out=str(tmp_path/'bad');rel.write_text('1 | 0:7 | 0')
    with pytest.raises(ValueError):cli.chemistry_relations(a)
    assert json.loads((tmp_path/'bad/failure.json').read_text())['status']=='error'


def test_actual_composed_g_f_and_optional_low_tables():
    a=np.arange(128)
    for base in ['F:2150','B:5','93']:
        spec=R.parse('1|0:0|G/'+base+'/45/23')[0]['target']
        want=R.target(R.parse_target(base),a)^np.array([(0x45>>(int(x)>>4))&1 for x in a])^np.array([(0x23>>(int(x)&15))&1 for x in a])
        assert np.array_equal(R.target(spec,a),want)
    for text in ['G/F:1/0/10000','G/F:1/'+('1'+'0'*32),'G/G/0/0']:
        with pytest.raises(ValueError):R.parse_target(text)


def test_negative_parity_mask_refuses_instead_of_looping():
    with pytest.raises(ValueError,match='nonnegative'):R.parity(np.array([-1]))
