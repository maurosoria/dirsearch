# Third-party licensing and distribution

dirsearch's original Python and Rust code is licensed under
`GPL-2.0-or-later`, as stated in LICENSE. Dependencies retain their own
copyrights and licenses.

## GPL version for combined distributions

Select **GPL version 3** when distributing dirsearch combined with its
Apache-2.0 dependencies. This applies to the Python application using Requests
and requests-toolbelt, and to the native extension linked with ring through
reqwest/rustls. It also applies to frozen executables, portable bundles, and
container images containing those combinations. The permission to select GPL
version 3 comes from the project's "version 2 or any later version" grant.
Apache-2.0 is compatible with GPL version 3, but not GPL version 2; no GPL
version 2 linking exception is granted here.

References: [Apache Software Foundation compatibility explanation](https://www.apache.org/licenses/GPL-compatibility.html)
and [GNU GPL compatibility FAQ](https://www.gnu.org/licenses/gpl-faq.en.html#v2v3Compatibility).

## Dependencies discussed in issue #1774

| Component | Version | License | Notices |
| --- | --- | --- | --- |
| Requests | 2.33.1 | Apache-2.0 | Upstream LICENSE and NOTICE are included with the main application. |
| requests-toolbelt | 1.0.0 | Apache-2.0 | Upstream LICENSE is included with the main application. |
| ring | 0.17.14 | Apache-2.0 AND ISC | Upstream LICENSE, LICENSE-BoringSSL, LICENSE-other-bits, and the once_cell license files are included with the native backend. |

The files under `licenses/` preserve upstream text verbatim. In the main source
tree, ring's notices are under `native/licenses/`. Both Python packages include
their applicable license files in distribution metadata. The main package also
carries the native sources and notices for source builds.

ring's license expression is a conjunction: its Apache-2.0 parts cannot be
replaced by choosing ISC. The included BoringSSL notice contains additional
copyright and license notices that must also be preserved.

This table records the dependencies raised in
[issue #1774](https://github.com/maurosoria/dirsearch/issues/1774), not a complete
dependency inventory. Other dependencies and bundled runtimes retain their
upstream licenses and notices. Installing dependencies as separate Python
packages preserves their installed metadata; frozen builds also copy installed
dependency metadata, including its license files.

## Redistributing builds

Keep applicable copyright, license, attribution, and NOTICE files for every
component actually included in a build. Include the GPL text and satisfy GPL
version 3's Corresponding Source requirements for the combined work, including
the relevant dependency sources and build scripts. A list of dependency names
or links alone does not satisfy those requirements.

Review the exact dependency versions, optional database drivers, embedded
Python runtime, and platform libraries used in each release. The notices here
clarify the reported compatibility issue; they are not a certification that
every possible binary distribution meets every dependency's obligations.

The metadata correction applies to releases made from this change onward;
existing release archives and tags are not rewritten.
