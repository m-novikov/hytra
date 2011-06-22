import ConfigParser
import time

### format spec parsing ### 

def _getSectionItemsDict(inifile):
    parser = ConfigParser.SafeConfigParser()
    parser.read( inifile )
    d = {}
    for section in parser.sections():
        d[section] = parser.items(section)
    return d 



### C++ Format Spec Generator ###
def _header_cpp(generatedFrom = '<unknown>', time = time.ctime()):
    s = '''//
// WARNING: autogenerated header - do not modify!
//
// generated from: %s
// generation time: %s
//
''' % (generatedFrom, time)
    return s

def _preamble_cpp( versions):
    s = ["#include <string>\n\n"]
    for version in versions:
        version = version.replace('.', '_')
        s.append('class version%s;\n' % version)
    return "".join(s)
 

def _section_cpp( section, default_version ):
    s='''template<typename revision = version%(rev)s>
struct %(name)s
{
    private:
	%(name)s();
};

''' % {'name': section, 'rev': default_version.replace('.', '_')}
    return s

def _items_cpp( section, items, version):
    s = ['''template<>
struct %(name)s<version%(rev)s>
{
''' % {'name': section, 'rev': version.replace('.', '_')}]

    for k,v in items:
        s.append('    const static std::string %s;\n' % k)

    s.append('};\n\n')

    for k,v in items:
        s.append('const std::string %(name)s<version%(rev)s>::%(key)s = "%(value)s";\n' % {'name': section, 'rev': version.replace('.', '_'), 'key': k, 'value': v})
    
    return "".join(s)

def generate_cpp_format_spec( inifile, default_version ):
    d = _getSectionItemsDict( inifile )
    version = d.pop('meta')[0][1]

    s = []
    s.append(_header_cpp( inifile ))
    s.append(' \n')
    s.append(_preamble_cpp( [version] ))
    for section in d.keys():
        s.append(_section_cpp( section, default_version ))

    for section in d.keys():
        s.append(_items_cpp( section, d[section], version) )
        s.append('\n\n')
    return "".join(s)
        


### Python Format Spec Generator
def _header_python(generatedFrom = '<unknown>', time = time.ctime()):
    s = '''##
## WARNING: autogenerated header - do not modify!
##
## generated from: %s
## generation time: %s
##
''' % (generatedFrom, time)
    return s

def _section_python( section ):
    '''Generate dictionary to store different revisions of the same section.'''
    return "%sRevisions = dict()\n" % section


def _items_python( section, items, version ):
    s = ["%sRevisions['%s'] = {\n" % (section, version)]

    for k,v in items:
        s.append("\t'%s': '%s',\n" % (k, v))

    s.append("\t}\n")
    return "".join(s)

def _default_revision_python( section, default_version ):
    return "%(name)s = %(name)sRevisions['%(rev)s']\n" % {'name': section, 'rev': default_version}

def generate_python_format_spec( inifile, default_version ):
    items = _getSectionItemsDict( inifile )
    version = items.pop('meta')[0][1]

    s = []
    s.append(_header_python( inifile ))
    s.append('\n')
    for section in items.keys():
        s.append(_section_python( section ))
    s.append('\n')

    for section in items.keys():
        s.append(_items_python( section, items[section], version) )
        s.append('\n\n')

    for section in items.keys():
        s.append(_default_revision_python( section, default_version ))
    return "".join(s)



if __name__ == '__main__':
    import sys
    inifile = sys.argv[1]
    py_out = sys.argv[2]
    cpp_out = sys.argv[3]
    default_version = sys.argv[4]

    pySpec = open(py_out, 'w')
    pySpec.write(generate_python_format_spec(inifile, default_version))
    pySpec.close()
    
    cppSpec = open(cpp_out, 'w')
    cppSpec.write(generate_cpp_format_spec(inifile, default_version))
    cppSpec.close()
    
